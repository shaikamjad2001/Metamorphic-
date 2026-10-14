"""Chat layer over the multi-agent system.

A question is planned by the Orchestrator (rule-based, or an LLM when configured), executed by the agents on the
frozen snapshot, and answered by the Synthesizer from the numbers the agents produced. Every step is streamed as
an event so the UI can draw the agent graph live. The LLM, when present, only plans and words the answer; all
figures come from the agents and tools.

Question types:
  trend     12-month trend for one slice                         -> full agent pipeline
  compare   two or more slices (cities, ZIPs, tiers, years, X vs metro) -> pipeline per slice
  rank      top / bottom ZIPs or cities by change, price or supply -> pipeline (per city for city ranking)
  listings  bedrooms / baths / sold vs for-sale on Kaggle listings -> ListingQueryTool
  macro     mortgage rate, Zillow ZHVI, FRED price and inventory -> MacroLookupTool
  testing   metamorphic-testing results                           -> results artifacts
  system    how the agents and loops work
  help      out of scope
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any, Iterator, Optional

import numpy as np
from pydantic import ValidationError

from backend import config, llm
from backend.agents.orchestrator import CriteriaError
from backend.nl_parser import parse_rules
from backend.pipeline import run_pipeline
from backend.schemas import SearchCriteria
from backend.snapshot import Snapshot, load_snapshot, month_add

INTENTS = ("trend", "compare", "rank", "listings", "macro", "testing", "system", "help")
LOW_CONFIDENCE = 0.7
SHAKY_NOTE = ("Low confidence usually means the area mixes distinct price clusters (e.g. Irving's ~$335K and ~$550K "
              "ZIPs), so the monthly median can jump between them; treat that change as unreliable.")
CRITERIA_KEYS = ("zipcodes", "cities", "tiers", "min_price", "max_price", "min_sqft", "max_sqft", "window_end")

DOMAIN = re.compile(
    r"price|home|house|listing|market|trend|zip|sq\s*ft|sqft|square|bed|bath|mortgage|rate|cost|expensive|cheap|"
    r"afford|value|inventory|supply|grow|change|fell|fall|drop|rise|rose|increase|decrease|apprec|real estate|"
    r"propert|condo|neighbo|area|cit(y|ies)|dallas|metro|buy|sell|sold|median|agent|test|mr\s?\d|relation|"
    r"violation|loop|tier|luxury|entry|zhvi|zillow|fred|fhfa|market|year|month|compare|vs|top|best|worst", re.I)

MR_VERDICT = {
    "MR1": "holds: aggregation and bootstrap are order-invariant.",
    "MR2": "violated through the controller, not the medians: duplicated rows inflate the bootstrap confidence "
           "(pseudo-replication), so the follow-up skips refinements. Resampling ZIP-month strata instead of rows "
           "removes every violation. An earlier crash on duplicate ZIP-months was found by this MR and fixed.",
    "MR3": "holds: no hard-coded dollar thresholds survive a USD to USD-thousands change.",
    "MR4": "ill-conceived for this estimator: temporal pooling spreads +$15K into neighbouring months, and band "
           "crossings change which records are summarised. The refined MR4R holds (0 violations). It also exposed "
           "an unstable outlier trim on 4-ZIP months, now fixed.",
    "MR5": "loop-emergent: a narrower band triggers a wider ±15% relaxation than the MR's ±$60K, so the source "
           "scans more. 0% when the control plan is pinned.",
    "MR6": "loop-emergent: the ZIP subset is sparse, so the auditor relaxes bands or adds neighbouring ZIPs. "
           "0% when pinned.",
    "MR7": "loop-emergent: the shifted window changes bootstrap confidence near the 0.85 target, so the "
           "refinement path differs. 0% when pinned.",
    "MR8": "holds: medians scale exactly by 1.25 and the hedonic step is scale-equivariant.",
    "MR4R": "holds: MR4 restated to exempt the pooling radius and band crossings.",
}

PLAN_SYSTEM = """You plan questions for a multi-agent system that analyses Dallas-area residential listing prices
from a frozen snapshot (Realtor.com ZIP-level monthly data 2022-12..{last}, Kaggle listings 2021-22, Zillow/FRED macro).
Return ONLY JSON:
{{"intent": one of trend|compare|rank|listings|macro|testing|system|help,
  "slices": [criteria, ...],            // one per thing to analyse; compare needs >= 2
  "rank_level": "zip"|"city", "rank_metric": "change"|"price"|"supply", "rank_order": "desc"|"asc", "top_n": int,
  "bedrooms": int|null, "bedrooms_min": bool, "status": "sold"|"for_sale"|null,
  "indicators": [subset of mortgage, zhvi, list_price, inventory, fhfa]}}
criteria keys (all optional): zipcodes [5-digit strings], cities [names], tiers [Entry, Value, Mid-Market, Upper,
Luxury], min_price, max_price (USD), min_sqft, max_sqft, window_end ("YYYY-MM", last month of a 12-month window,
<= {last}). Known cities: {cities}.
Use "help" only for questions unrelated to Dallas housing, these agents or their tests."""

ANSWER_SYSTEM = """You are the Synthesizer agent of a Dallas housing-trends system. Answer the user's question
using ONLY the facts JSON (computed by the other agents from real data). Quote numbers exactly as given, keep it to
2-6 sentences of plain text, say which slice and window the numbers refer to, and mention a caveat if the facts
include one that matters (low confidence, relaxed bands, added ZIPs, pooled months, listing data being 2021-22).
If the facts do not answer the question, say so and say what the data can answer."""


# --------------------------------------------------------------------------- helpers

def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def money(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.2f}M"
    return f"${x:,.0f}"


def pct(x: Optional[float], d: int = 1) -> str:
    return "n/a" if x is None else f"{x:+.{d}f}%"


def band_text(c: dict) -> str:
    parts = []
    lo, hi = c.get("min_price"), c.get("max_price")
    if lo is not None and hi is not None:
        parts.append(f"{money(lo)}–{money(hi)}")
    elif hi is not None:
        parts.append(f"under {money(hi)}")
    elif lo is not None:
        parts.append(f"over {money(lo)}")
    if c.get("min_sqft") or c.get("max_sqft"):
        parts.append(f"{int(c.get('min_sqft') or 0):,}–{int(c['max_sqft']):,} sqft" if c.get("max_sqft")
                     else f"{int(c['min_sqft']):,}+ sqft")
    return ", ".join(parts)


def city_name(c: str) -> str:
    return re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), c or "")


def scope_text(c: dict) -> str:
    if c.get("zipcodes"):
        z = c["zipcodes"]
        s = "ZIP " + ", ".join(z[:5]) + ("…" if len(z) > 5 else "") if len(z) <= 5 else f"{len(z)} ZIPs"
    elif c.get("cities"):
        s = " & ".join(city_name(x) for x in c["cities"])
    else:
        s = "Dallas metro"
    if c.get("tiers"):
        s += " · " + "/".join(c["tiers"]) + " tier"
    return s


def label(c: dict) -> str:
    if c.get("label"):
        return c["label"]
    b = band_text(c)
    return scope_text(c) + (f" ({b})" if b else "")


def ev(agent: str, action: str, **detail) -> dict:
    return {"type": "event", "run": None, "event": {"agent": agent, "action": action, "loop": None,
                                                     "iteration": None, "detail": detail, "elapsed_ms": 0}}


def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        return _clean(o.item())
    return o


# --------------------------------------------------------------------------- planning

def classify(q: str, crit: dict) -> str:
    ql = q.lower()
    if re.search(r"\bmrs?\b|\bmr\s?\d|metamorphic|violat|\brelations?\b|harness|wilson|confidence interval|"
                 r"\btest(s|ing|ed)?\b", ql):
        return "testing"
    if re.search(r"how (does|do|did) (this|the|your|these)|what (are|is) the agents?|which agents|architecture|"
                 r"workflow|feedback loop|refinement loop|explain (the|your) (system|agents)|who are you", ql):
        return "system"
    if re.search(r"mortgage|interest rate|zhvi|zillow|\bfred\b|fhfa|\bhpi\b|macro|home value index", ql):
        return "macro"
    if re.search(r"\d\s*\+?\s*(-| )?(bed|br\b|bedroom|bath)|bedrooms?|bathrooms?|acre|lot size|kaggle|"
                 r"sold (homes|houses|listings)|individual listings?|for[- ]sale listings", ql):
        return "listings"
    if re.search(r"\bvs\.?\b|versus|compar|difference between|against the metro|relative to", ql):
        return "compare"
    if re.search(r"\bwhich (zip|zips|zip ?codes?|city|cities|neighbou?rhoods?|areas?|suburbs?)\b|\btop \d*|"
                 r"\bbest\b|\bworst\b|\bmost\b|\bleast\b|fastest|slowest|highest|lowest|\brank|cheapest|"
                 r"priciest|most expensive", ql):
        return "rank"
    if not DOMAIN.search(ql) and not crit:
        return "help"
    return "trend"


def _rules_plan(q: str, snap: Snapshot, context: Optional[dict]) -> dict:
    crit, notes = parse_rules(q, snap)
    intent = classify(q, crit)
    ql = q.lower()
    follow_up = bool(re.match(r"\s*(what|how) about|\s*and\b|\s*same for|\s*now\b", ql))
    if context and follow_up and intent in ("trend", "help"):
        intent = context.get("intent", "trend")
        inherited = {k: v for k, v in (context.get("base") or {}).items()
                     if k in ("min_price", "max_price", "min_sqft", "max_sqft", "window_end") and k not in crit}
        crit = {**inherited, **crit}
        notes.append("follow-up: kept the previous question's type, price band and window")

    plan: dict = {"intent": intent, "planner": "rules", "notes": notes, "base": crit}
    scope_keys = ("zipcodes", "cities", "tiers")
    base = {k: v for k, v in crit.items() if k not in scope_keys}

    if intent == "compare":
        years = sorted(set(re.findall(r"\b(20\d{2})\b", q)))
        slices = []
        if len(crit.get("cities") or []) >= 2:
            order = sorted(crit["cities"], key=lambda c: ql.find(c.lower()))
            slices = [{**base, "cities": [c]} for c in order]
        elif len(crit.get("zipcodes") or []) >= 2:
            slices = [{**base, "zipcodes": [z]} for z in crit["zipcodes"]]
        elif len(crit.get("tiers") or []) >= 2:
            slices = [{**base, "tiers": [t]} for t in crit["tiers"]]
        elif len(years) >= 2:
            last = snap.months[-1]
            no_win = {k: v for k, v in crit.items() if k != "window_end"}
            slices = [{**no_win, "window_end": min(f"{y}-12", last), "label": f"{scope_text(no_win)} · {y}"}
                      for y in years]
        elif any(crit.get(k) for k in scope_keys):
            slices = [crit, base]
        if len(slices) >= 2:
            plan["slices"] = slices
        else:
            plan["intent"] = "trend"
            notes.append("found fewer than two things to compare; showing a single trend")
    if plan["intent"] in ("trend", "listings", "macro", "rank"):
        plan["slices"] = [crit]
    if plan["intent"] == "rank":
        plan["rank_level"] = "city" if re.search(r"\b(city|cities|town|towns|suburbs?)\b", ql) else "zip"
        if re.search(r"expensive|cheap|priciest|afford|price level|highest price|lowest price|most costly", ql):
            metric = "price"
        elif re.search(r"listings|inventory|supply|homes for sale|active", ql):
            metric = "supply"
        else:
            metric = "change"
        plan["rank_metric"] = metric
        asc = re.search(r"fell|drop|declin|decreas|worst|least|lowest|slowest|cheap|afford|weak|fewest|lost", ql)
        plan["rank_order"] = "asc" if asc else "desc"
        n = re.search(r"\btop\s+(\d+)|\b(\d+)\s+(zips?|zip codes|cities|areas)", ql)
        plan["top_n"] = min(15, int(next(g for g in n.groups() if g and g.isdigit()))) if n else 5
    if plan["intent"] == "listings":
        b = re.search(r"(\d)\s*(\+|or more)?\s*(?:-|\s)?(?:bed|br\b|bedroom)", ql)
        plan["bedrooms"] = int(b.group(1)) if b else None
        plan["bedrooms_min"] = bool(b and (b.group(2) or re.search(r"at least\s*\d\s*bed", ql)))
        plan["status"] = "sold" if re.search(r"\bsold\b", ql) else "for_sale" if re.search(r"for sale|on the market", ql) else None
    if plan["intent"] == "macro":
        ind = []
        for key, pat in (("mortgage", r"mortgage|interest rate"), ("zhvi", r"zhvi|zillow|home value"),
                         ("list_price", r"list(ing)? price|fred"), ("inventory", r"inventory|active listings|supply"),
                         ("fhfa", r"fhfa|\bhpi\b")):
            if re.search(pat, ql):
                ind.append(key)
        plan["indicators"] = ind or ["mortgage", "zhvi", "list_price", "inventory"]
    return plan


def _llm_plan(q: str, snap: Snapshot, context: Optional[dict]) -> Optional[dict]:
    cities = sorted({g.get("city") for g in snap.geo.values() if g.get("city")})
    system = PLAN_SYSTEM.format(last=snap.months[-1], cities=", ".join(cities))
    user = q if not context else f"Previous question plan: {json.dumps(context)}\nNew question: {q}"
    raw = llm.extract_json(llm.complete(system, user, json_mode=True))
    intent = raw.get("intent")
    if intent not in INTENTS:
        return None
    slices = []
    for s in raw.get("slices") or [{}]:
        c = {k: v for k, v in (s or {}).items() if k in CRITERIA_KEYS and v not in (None, [], "")}
        if c.get("window_end") and c["window_end"] > snap.months[-1]:
            c["window_end"] = snap.months[-1]
        SearchCriteria(**c)
        slices.append(c)
    plan = {"intent": intent, "planner": f"llm ({llm.provider()})", "notes": [], "slices": slices or [{}],
            "base": slices[0] if slices else {}}
    if intent == "compare" and len(plan["slices"]) < 2:
        return None
    plan["rank_level"] = raw.get("rank_level") if raw.get("rank_level") in ("zip", "city") else "zip"
    plan["rank_metric"] = raw.get("rank_metric") if raw.get("rank_metric") in ("change", "price", "supply") else "change"
    plan["rank_order"] = raw.get("rank_order") if raw.get("rank_order") in ("asc", "desc") else "desc"
    plan["top_n"] = max(1, min(15, int(raw.get("top_n") or 5)))
    plan["bedrooms"] = raw.get("bedrooms")
    plan["bedrooms_min"] = bool(raw.get("bedrooms_min"))
    plan["status"] = raw.get("status") if raw.get("status") in ("sold", "for_sale") else None
    plan["indicators"] = [i for i in (raw.get("indicators") or []) if i in ("mortgage", "zhvi", "list_price", "inventory", "fhfa")] \
        or ["mortgage", "zhvi", "list_price", "inventory"]
    return plan


# --------------------------------------------------------------------------- execution

def _summary(r, lab: str) -> dict:
    t, d = r.trend, r.diagnostics
    s = t.monthly_series
    zr = [z.model_dump() for z in t.zip_rankings]
    return {
        "label": lab, "criteria": r.criteria.model_dump(exclude_none=True),
        "window": [t.window_start, t.window_end], "method": t.method,
        "start_price": s[0].median_price, "end_price": s[-1].median_price,
        "change_pct": t.trend_change_pct, "cagr_pct": t.annual_cagr_estimate,
        "start_active": s[0].active_count, "end_active": s[-1].active_count,
        "start_ppsf": s[0].median_price_per_sqft, "end_ppsf": s[-1].median_price_per_sqft,
        "divergence_vs_zhvi": t.macro_divergence_score,
        "confidence": t.confidence, "confidence_target": r.criteria.confidence_target,
        "audit_passed": t.quality_audit_passed, "n_zips": len(d["zips_in_scope"]) + len(r.control.added_zips),
        "control": r.control.model_dump(), "feedback_cycles": d["feedback_cycles"],
        "refinements_attempted": d["refinements_attempted"], "caveats": r.caveats, "narrative": r.narrative,
        "series": [{"month": m.month, "median_price": m.median_price, "active_count": m.active_count,
                    "median_ppsf": m.median_price_per_sqft} for m in s],
        "zip_rankings": zr,
        "runtime_ms": d["runtime_ms"],
    }


def _run(c: dict, snap: Snapshot, seed: int, idx: int, lab: str) -> Iterator[dict]:
    yield {"type": "run_start", "run": idx, "label": lab, "criteria": c}
    try:
        r = run_pipeline(SearchCriteria(**c), snap, seed)
    except (CriteriaError, ValidationError) as e:
        yield {"type": "run_error", "run": idx, "label": lab, "error": str(e).split("\n")[0]}
        return
    for e in r.events:
        yield {"type": "event", "run": idx, "event": e.model_dump()}
    yield {"type": "run_result", "run": idx, "summary": _summary(r, lab)}


def _scope_zips(snap: Snapshot, c: dict) -> set[str]:
    zips = set(snap.geo)
    if c.get("zipcodes"):
        zips &= set(c["zipcodes"])
    if c.get("cities"):
        w = {x.lower() for x in c["cities"]}
        zips &= {z for z in zips if (snap.geo[z].get("city") or "").lower() in w}
    if c.get("tiers"):
        w = {x.lower() for x in c["tiers"]}
        zips &= {z for z in zips if (snap.geo[z].get("price_tier") or "").lower() in w}
    return zips


def listing_query(snap: Snapshot, c: dict, plan: dict) -> dict:
    df = snap.listings
    zips = _scope_zips(snap, c)
    df = df[df["zipcode"].isin(zips)]
    if plan.get("bedrooms"):
        df = df[df["bedrooms"] >= plan["bedrooms"]] if plan.get("bedrooms_min") else df[df["bedrooms"] == plan["bedrooms"]]
    if plan.get("status"):
        df = df[df["status"] == plan["status"]]
    if c.get("min_price") is not None:
        df = df[df["price"] >= c["min_price"]]
    if c.get("max_price") is not None:
        df = df[df["price"] <= c["max_price"]]
    if c.get("min_sqft") is not None:
        df = df[df["sqft"] >= c["min_sqft"]]
    if c.get("max_sqft") is not None:
        df = df[df["sqft"] <= c["max_sqft"]]
    by_beds = []
    for b, g in df.dropna(subset=["bedrooms"]).assign(b=lambda x: x["bedrooms"].clip(upper=6).astype(int)).groupby("b"):
        by_beds.append({"beds": f"{b}+" if b == 6 else str(b), "n": int(len(g)), "median_price": _f(g["price"].median())})
    top = df.groupby("zipcode").size().sort_values(ascending=False).head(5)
    return {
        "scope": label(c), "n": int(len(df)), "zips": len(zips),
        "filters": {"bedrooms": plan.get("bedrooms"), "bedrooms_min": plan.get("bedrooms_min"), "status": plan.get("status")},
        "by_status": {k: int(v) for k, v in df["status"].value_counts().items()},
        "median_price": _f(df["price"].median()), "median_sqft": _f(df["sqft"].median()),
        "median_ppsf": _f(df["price_per_sqft"].median()), "by_bedrooms": by_beds,
        "top_zips": [{"zipcode": z, "city": snap.geo.get(z, {}).get("city"), "n": int(n)} for z, n in top.items()],
        "data_note": "Kaggle USA Real Estate listings (Realtor.com, scraped 2021-22); not part of the monthly window.",
    }


MACRO_COLS = {"mortgage": ("mortgage_rate_30y", "30-year mortgage rate", "%"),
              "zhvi": ("zhvi_metro", "Zillow home value index (DFW)", "$"),
              "list_price": ("fred_median_listing_price", "Realtor.com median list price (DFW, FRED)", "$"),
              "inventory": ("fred_active_listing_count", "Active listings (DFW, FRED)", "#"),
              "fhfa": ("fhfa_hpi_quarterly", "FHFA house price index (quarterly)", "idx")}


def macro_query(snap: Snapshot, c: dict, plan: dict) -> dict:
    end = c.get("window_end") or config.DEFAULT_WINDOW_END
    start = month_add(end, -(config.WINDOW_MONTHS - 1))
    m = snap.macro[(snap.macro["month"] >= start) & (snap.macro["month"] <= end)]
    out = {"window": [start, end], "indicators": []}
    for key in plan["indicators"]:
        col, name, unit = MACRO_COLS[key]
        s = m[["month", col]].dropna()
        if s.empty:
            continue
        a, b = float(s[col].iloc[0]), float(s[col].iloc[-1])
        out["indicators"].append({
            "key": key, "name": name, "unit": unit, "start_month": s["month"].iloc[0], "end_month": s["month"].iloc[-1],
            "start": a, "end": b, "change": b - a if unit == "%" else (b / a - 1) * 100,
            "change_kind": "points" if unit == "%" else "percent",
            "series": [{"month": r.month, "value": _f(getattr(r, col))} for r in s.itertuples()],
        })
    return out


def testing_query(q: str) -> dict:
    def read(name):
        p = os.path.join(config.RESULTS_DIR, name)
        return json.load(open(p)) if os.path.exists(p) else None
    h, dg = read("headline_results.json"), read("diagnosis.json")
    if h is None:
        return {"available": False}
    nat = {r["mr"]: r for r in h["results"]["natural"]}
    pin = {r["mr"]: r for r in h["results"].get("pinned", [])}
    asked = [f"MR{a}{'R' if b else ''}" for a, b in re.findall(r"\bmr\s?(\d)(r)?\b", q.lower())]
    rows = [{"mr": k, "name": v["name"], "family": v["family"], "violations": v["violations"], "runs": v["n_executions"],
             "rate": v["violation_rate"], "ci95": v["ci95"], "pinned_violations": pin.get(k, {}).get("violations"),
             "verdict": MR_VERDICT.get(k)} for k, v in nat.items()]
    return {"available": True, "asked": [a for a in asked if a in nat], "rows": rows,
            "top3": (dg or {}).get("top3"), "seeds": h["seeds"], "bases": h["base_inputs"]["n"]}


CASE_VERB = re.compile(r"\b(run|test|show|reproduce|demo|try|check|execute|replay|example|demonstrate)\b")


def case_request(q: str) -> Optional[dict]:
    """'test MR5', 'show me an MR2 violation on base 7 seed 101 pinned' -> a live harness case."""
    ql = q.lower()
    m = re.search(r"\bmr\s?(\d)(r)?\b", ql)
    if not m or not CASE_VERB.search(ql):
        return None
    if re.search(r"\b(why|which|rate|how many|diagnos\w*|results?)\b", ql) and \
            not re.search(r"\b(run|reproduce|demo|replay|show me|live)\b", ql):
        return None
    b = re.search(r"\bbase\s*(?:input\s*)?#?\s*b?(\d{1,2})\b|\bb(\d{2})\b", ql)
    s = re.search(r"\bseed\s*(\d+)", ql)
    return {"mr": f"MR{m.group(1)}{'R' if m.group(2) else ''}",
            "base": int(b.group(1) or b.group(2)) - 1 if b else None,
            "seed": int(s.group(1)) if s else None,
            "mode": "pinned" if re.search(r"\bpinned?\b", ql) else "natural",
            "want": "hold" if re.search(r"\b(holds?|passing|passes|pass)\b", ql) else "violation"}


def recorded_cases(mr: Optional[str] = None) -> list[dict]:
    p = os.path.join(config.RESULTS_DIR, "cases.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if mr is None or r["mr"] == mr]


def _pick_case(req: dict, recs: list[dict], seeds) -> tuple[int, int, Optional[dict], str]:
    mine = [r for r in recs if r["mode"] == req["mode"]]
    if req["base"] is not None:
        mine = [r for r in mine if r["base_idx"] == req["base"]]
    if req["seed"] is not None:
        mine = [r for r in mine if r["seed"] == req["seed"]]
    want = [r for r in mine if (r.get("violated") is True) == (req["want"] == "violation") and r.get("applicable", True)]
    if want:
        r = want[0]
        why = (f"picked a recorded {'violating' if req['want'] == 'violation' else 'passing'} case "
               f"({len(want)} of {len(mine)} matching cases)")
        return r["base_idx"], r["seed"], r, why
    if mine:
        r = mine[0]
        return r["base_idx"], r["seed"], r, (f"no recorded {req['want']} matches, so this is a representative case")
    return req["base"] or 0, req["seed"] or seeds[0], None, "no recorded case found; running it fresh"


def run_mr_case(req: dict, facts: dict) -> Iterator[dict]:
    from mt import harness
    from mt.relations import BY_ID
    if req["mr"] not in BY_ID:
        yield ev("Orchestrator", "unknown_relation", mr=req["mr"])
        facts["case"] = {"error": f"unknown relation {req['mr']}"}
        return
    if not harness._STATE:
        harness._init()
    snap, bases = harness._STATE["snapshot"], harness._STATE["bases"]
    if req["base"] is not None and not 0 <= req["base"] < len(bases):
        req["base"] = None
    recs = recorded_cases(req["mr"])
    bi, seed, rec, why = _pick_case(req, recs, config.SEEDS)
    mr, base = BY_ID[req["mr"]], bases[bi]
    other = next((r for r in recs if r["base_idx"] == bi and r["seed"] == seed and r["mode"] != req["mode"]), None)
    yield ev("Orchestrator", "selected_mr_case", mr=mr.id, base=base.label, seed=seed, mode=req["mode"], reason=why)

    yield {"type": "run_start", "run": 0, "label": f"Source · {base.label}", "criteria": base.model_dump(exclude_none=True)}
    src = run_pipeline(base, snap, seed)
    for e in src.events:
        yield {"type": "event", "run": 0, "event": e.model_dump()}
    yield {"type": "run_result", "run": 0, "summary": _summary(src, f"Source · {base.label}")}

    snap2, crit2, info = mr.transform(snap, base, seed)
    yield ev("Orchestrator", "applied_transformation", mr=mr.id, transformation=mr.transformation,
             **{k: v for k, v in info.items() if isinstance(v, (int, float, str))})
    flab = f"Follow-up · {mr.id}" + (" (pinned)" if req["mode"] == "pinned" else "")
    yield {"type": "run_start", "run": 1, "label": flab, "criteria": crit2.model_dump(exclude_none=True)}
    fol = run_pipeline(crit2, snap2, seed, forced=src.control if req["mode"] == "pinned" else None)
    for e in fol.events:
        yield {"type": "event", "run": 1, "event": e.model_dump()}
    yield {"type": "run_result", "run": 1, "summary": _summary(fol, flab)}

    chk = mr.check(src, fol, info)
    violated = None if chk is None else bool(chk.violated)
    diverged = harness._fingerprint(src) != harness._fingerprint(fol)
    yield ev("Orchestrator", "checked_relation", mr=mr.id,
             verdict="outside subdomain" if chk is None else "violated" if violated else "holds",
             max_deviation=None if chk is None else chk.max_deviation, path_diverged=diverged)
    fp = lambda r: {**harness._fingerprint(r), "confidence": r.trend.confidence,
                    "audit_passed": r.trend.quality_audit_passed}
    facts["case"] = {
        "mr": mr.catalog(), "base_idx": bi, "base": base.label, "seed": seed, "mode": req["mode"], "why": why,
        "transform_info": info, "applicable": chk is not None, "violated": violated,
        "max_deviation": None if chk is None else chk.max_deviation,
        "detail": None if chk is None else chk.detail, "path_diverged": diverged,
        "source": fp(src), "follow": fp(fol),
        "recorded_violated": rec.get("violated") if rec else None,
        "matches_recorded": None if rec is None else rec.get("violated") == violated,
        "other_mode": None if other is None else {"mode": other["mode"], "violated": other.get("violated")},
        "verdict": MR_VERDICT.get(mr.id),
        "series": {"source": [m.model_dump() for m in src.trend.monthly_series],
                   "follow": [m.model_dump() for m in fol.trend.monthly_series]},
        "currency_unit": fol.trend.currency_unit,
    }


# --------------------------------------------------------------------------- answers

def _loops_text(s: dict) -> str:
    bits = []
    if s["feedback_cycles"]:
        how = []
        if s["control"]["relaxation_level"]:
            how.append(f"widened the price band ±{int(s['control']['relaxation_factor'] * 100)}%")
        if s["control"]["added_zips"]:
            how.append(f"added ZIPs {', '.join(s['control']['added_zips'])}")
        bits.append(f"the Quality Auditor sent the Data Scout back {s['feedback_cycles']}× ({'; '.join(how) or 'retried'})")
    if s["refinements_attempted"]:
        kept = s["control"]["refinements"]
        bits.append("the Synthesizer requested " + ", ".join(r.replace("_", " ") for r in s["refinements_attempted"])
                    + (f" and kept {', '.join(r.replace('_', ' ') for r in kept)}" if kept and kept != s["refinements_attempted"] else ""))
    return ("Loops: " + "; ".join(bits) + ".") if bits else "No loop was needed: coverage and confidence passed on the first pass."


def _trend_sentence(s: dict) -> str:
    direction = "rose" if (s["change_pct"] or 0) > 0 else "fell" if (s["change_pct"] or 0) < 0 else "was flat"
    return (f"{s['label']}, {s['window'][0]} to {s['window'][1]}: the median list price {direction} from "
            f"{money(s['start_price'])} to {money(s['end_price'])} ({pct(s['change_pct'], 2)}), "
            f"active listings {s['start_active']:,} → {s['end_active']:,}")


def template_answer(plan: dict, facts: dict) -> str:
    it = plan["intent"]
    if it == "help":
        return ("I answer questions about Dallas-area home listing prices from a frozen snapshot of real data "
                "(Realtor.com ZIP-level monthly listings 2022-12 to 2026-09, Kaggle listings, Zillow and FRED). "
                "Try: “How did prices change in Plano?”, “Compare Frisco vs McKinney”, “Which ZIPs fell the most?”, "
                "“3 bedroom homes in 75204”, “What happened to mortgage rates?”, or “Which MR was violated most?”.")
    if it == "system":
        return ("Five agents and a supervisor answer each question. The Orchestrator turns it into criteria; the Data "
                "Scout slices the frozen snapshot; the Quality Auditor checks every month has ≥ 4 ZIPs and ≥ 40 active "
                "listings and, if not, sends the Scout back to widen the price band (±15/30/45%) or add neighbouring "
                "ZIPs (feedback loop); the Trend Specialist picks a hedonic or stratified-median estimator from the "
                "listing mix; the Synthesizer scores confidence with a seeded bootstrap and, below 0.85, sends the "
                "trend back for outlier trimming or month pooling (refinement loop). The Loop Supervisor caps both "
                "loops at 3 cycles and 12 seconds. Ask a market question to watch it run.")
    runs = [r for r in facts.get("runs", []) if r]
    if it == "trend":
        if not runs:
            return "I could not analyse that slice: " + "; ".join(facts.get("errors") or ["no data"]) + "."
        s = runs[0]
        top = [z for z in s["zip_rankings"] if z["end_active"] >= 10][:3]
        conf = (f"Confidence {s['confidence']:.2f} "
                + ("(meets the 0.85 target)." if s["confidence"] >= s["confidence_target"] else "(below the 0.85 target, so read it with care)."))
        if s["confidence"] < LOW_CONFIDENCE:
            conf += " " + SHAKY_NOTE
        txt = (_trend_sentence(s) + f". Annualised that is {pct(s['cagr_pct'], 2)}; median $/sqft "
               f"{s['start_ppsf'] or 0:,.0f} → {s['end_ppsf'] or 0:,.0f}. Method: {s['method'].replace('_', ' ')} over "
               f"{s['n_zips']} ZIPs. {conf}")
        if top and len(s["zip_rankings"]) > 1:
            txt += " Strongest ZIPs: " + ", ".join(f"{z['zipcode']} {z['city'] or ''} ({pct(z['change_pct'])})" for z in top) + "."
        return txt + "\n\n" + _loops_text(s)
    if it == "compare":
        if len(runs) < 2:
            return "I could only analyse " + (runs[0]["label"] if runs else "none") + " of the slices: " + "; ".join(facts.get("errors") or []) + "."
        lines = [f"• {_trend_sentence(s)}; confidence {s['confidence']:.2f}"
                 + (" ⚠ low." if s["confidence"] < LOW_CONFIDENCE else ".") for s in runs]
        valid = [s for s in runs if s["change_pct"] is not None]
        best = max(valid, key=lambda s: s["change_pct"])
        worst = min(valid, key=lambda s: s["change_pct"])
        pricier = max(runs, key=lambda s: s["end_price"] or 0)
        head = (f"{best['label']} moved most ({pct(best['change_pct'], 2)}) and {worst['label']} least "
                f"({pct(worst['change_pct'], 2)}). {pricier['label']} has the highest current median "
                f"({money(pricier['end_price'])}).")
        loops = [f"{s['label']}: {_loops_text(s)}" for s in runs if s["feedback_cycles"] or s["refinements_attempted"]]
        shaky = any(s["confidence"] < LOW_CONFIDENCE for s in runs)
        return (head + "\n\n" + "\n".join(lines) + ("\n\n" + "\n".join(loops) if loops else "")
                + ("\n\n" + SHAKY_NOTE if shaky else ""))
    if it == "rank":
        rk = facts.get("ranking") or {}
        items = rk.get("items") or []
        if not items:
            return "No ZIPs or cities had enough data to rank."
        metric = {"change": "12-month change", "price": "current median list price", "supply": "active listings"}[rk["metric"]]
        order = "lowest" if rk["order"] == "asc" else "highest"
        level = "cities" if rk["level"] == "city" else "ZIPs"
        head = f"{order.capitalize()} {level} by {metric} in {rk['scope']} ({rk['window'][0]} to {rk['window'][1]}):"
        lines, shaky = [], False
        for i, x in enumerate(items, 1):
            val = pct(x["change_pct"]) if rk["metric"] == "change" else money(x["end_price"]) if rk["metric"] == "price" else f"{x['end_active']:,} active"
            flag = ""
            if x.get("confidence") is not None and x["confidence"] < LOW_CONFIDENCE:
                flag, shaky = f" ⚠ low confidence {x['confidence']:.2f}", True
            lines.append(f"{i}. {x['name']}: {val} ({money(x['start_price'])} → {money(x['end_price'])}, "
                         f"{x['end_active']:,} active){flag}")
        notes = [n for n in (rk.get("note"), SHAKY_NOTE if shaky else None) if n]
        return head + "\n" + "\n".join(lines) + ("\n\n" + " ".join(notes) if notes else "")
    if it == "listings":
        L = facts["listings"]
        if not L["n"]:
            return f"No Kaggle listings match that in {L['scope']}."
        f = L["filters"]
        what = (f"{f['bedrooms']}{'+' if f['bedrooms_min'] else ''}-bedroom " if f["bedrooms"] else "") + \
               ({"sold": "sold ", "for_sale": "for-sale "}.get(f["status"] or "", "")) + "listings"
        beds = ", ".join(f"{b['beds']} bd {money(b['median_price'])} (n={b['n']})" for b in L["by_bedrooms"])
        return (f"{L['n']:,} {what} in {L['scope']}: median price {money(L['median_price'])}, median size "
                f"{(L['median_sqft'] or 0):,.0f} sqft, median {money(L['median_ppsf'])}/sqft. By bedrooms: {beds}. "
                f"Status: {', '.join(f'{k} {v:,}' for k, v in L['by_status'].items())}.\n\nNote: {L['data_note']}")
    if it == "macro":
        M = facts["macro"]
        parts = []
        for i in M["indicators"]:
            if i["unit"] == "%":
                parts.append(f"{i['name']}: {i['start']:.2f}% → {i['end']:.2f}% ({i['change']:+.2f} points)")
            elif i["unit"] == "$":
                parts.append(f"{i['name']}: {money(i['start'])} → {money(i['end'])} ({pct(i['change'])})")
            else:
                parts.append(f"{i['name']}: {i['start']:,.0f} → {i['end']:,.0f} ({pct(i['change'])})")
        return f"From {M['window'][0]} to {M['window'][1]} (published series in the snapshot):\n" + "\n".join(f"• {p}" for p in parts)
    if it == "testing" and facts.get("case") and "error" not in facts["case"]:
        C = facts["case"]
        mr, s, f = C["mr"], C["source"], C["follow"]
        verdict = ("OUTSIDE the relation's subdomain (not counted)" if not C["applicable"]
                   else "VIOLATED" if C["violated"] else "HOLDS")
        def path(x):
            ref = ", ".join(r.replace("temporal_", "").replace("_", " ") for r in x["refinements"]) or "none"
            return (f"band relaxation level {x['relaxation_level']}, {len(x['added_zips'])} added ZIPs, "
                    f"method {x['method'].replace('_', ' ')}, refinements {ref}, confidence {x['confidence']:.3f}")
        out = [f"Live test of {mr['id']} ({mr['name']}) on base input {C['base']}, seed {C['seed']}, {C['mode']} mode "
               f"({C['why']}).",
               f"Transformation: {mr['transformation']}\nRelation: {mr['relation']}\nTolerance: {mr['tolerance']}",
               f"Result: {verdict}" + (f" (max deviation {C['max_deviation']:.4g})" if C["max_deviation"] is not None
                                       and math.isfinite(C["max_deviation"]) else "")
               + ("" if C["matches_recorded"] is None else
                  " — same verdict as the recorded harness run." if C["matches_recorded"] else
                  " — differs from the recorded harness run."),
               f"• Source run: {path(s)}\n• Follow-up run: {path(f)}"]
        if C["path_diverged"]:
            out.append("The control path diverged: the follow-up run made different loop decisions from the source run.")
        if C["other_mode"] is not None and C["other_mode"]["violated"] is not None:
            om = C["other_mode"]
            out.append(f"Recorded {om['mode']}-mode result for this same case: "
                       f"{'violated' if om['violated'] else 'holds'}.")
        if C.get("detail"):
            d = {k: v for k, v in C["detail"].items() if not isinstance(v, (list, dict))}
            if d:
                out.append("Check detail: " + ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in list(d.items())[:5]))
        if C.get("verdict"):
            out.append(f"Diagnosis for {mr['id']} across all 96 runs: {C['verdict']}")
        return "\n\n".join(out)
    if it == "testing":
        T = facts["testing"]
        if not T["available"]:
            return "The metamorphic results have not been generated yet: run `python run_headline_results.py`."
        rows = {r["mr"]: r for r in T["rows"]}
        pick = T["asked"] or (T["top3"] or [])
        head = (f"Each relation ran on {T['bases']} base inputs × seeds {', '.join(map(str, T['seeds']))} "
                f"(96 executions), natural mode.")
        lines = []
        for k in pick:
            r = rows[k]
            lines.append(f"• {k} {r['name']}: {r['violations']}/{r['runs']} ({r['rate'] * 100:.1f}%, 95% CI "
                         f"{r['ci95'][0] * 100:.1f}–{r['ci95'][1] * 100:.1f}%); with the loops pinned "
                         f"{r['pinned_violations']}/{r['runs']}. Diagnosis: {r['verdict']}")
        if not T["asked"]:
            held = [k for k, r in rows.items() if r["violations"] == 0]
            head += f" Most violated: {', '.join(pick)}. Holding: {', '.join(held)}."
        return head + "\n" + "\n".join(lines)
    return "Done."


def llm_answer(q: str, plan: dict, facts: dict) -> str:
    slim = json.loads(json.dumps(_clean(facts), default=str))
    for r in slim.get("runs", []):
        if r:
            r.pop("series", None)
            r["zip_rankings"] = r.get("zip_rankings", [])[:5]
            r.pop("narrative", None)
    if isinstance(slim.get("case"), dict):
        slim["case"].pop("series", None)
    return llm.complete(ANSWER_SYSTEM, f"Question: {q}\nQuestion type: {plan['intent']}\nFacts: {json.dumps(slim)[:12000]}")


# --------------------------------------------------------------------------- entry point

def chat_stream(question: str, seed: int = 42, context: Optional[dict] = None) -> Iterator[dict]:
    t0 = time.perf_counter()
    snap = load_snapshot()
    q = question.strip()
    yield ev("Orchestrator", "received_question", question=q)

    plan = None
    if llm.provider():
        yield ev("Orchestrator", "planning_with_llm", provider=llm.provider())
        try:
            plan = _llm_plan(q, snap, context)
        except Exception as e:  # LLM is optional; never fail the chat on it
            yield ev("Orchestrator", "llm_plan_failed", error=type(e).__name__)
    if plan is None:
        plan = _rules_plan(q, snap, context)
    if case_request(q):
        plan = {**plan, "intent": "testing", "slices": []}
    yield {"type": "plan", "plan": _clean({**plan, "labels": [label(s) for s in plan.get("slices", [])]})}
    yield ev("Orchestrator", "planned_question", intent=plan["intent"], planner=plan["planner"],
             slices=[label(s) for s in plan.get("slices", [])])

    facts: dict = {"intent": plan["intent"], "runs": [], "errors": []}
    it = plan["intent"]

    def collect(stream):
        for item in stream:
            if item["type"] == "run_result":
                facts["runs"].append(item["summary"])
            elif item["type"] == "run_error":
                facts["errors"].append(f"{item['label']}: {item['error']}")
            yield item

    if it in ("trend", "compare"):
        for i, c in enumerate(plan["slices"]):
            yield from collect(_run(c, snap, seed, i, label(c)))
    elif it == "rank":
        c = plan["slices"][0]
        metric, asc, n = plan["rank_metric"], plan["rank_order"] == "asc", plan["top_n"]
        key = {"change": "change_pct", "price": "end_price", "supply": "end_active"}[metric]
        if plan["rank_level"] == "city":
            counts: dict[str, int] = {}
            for z in _scope_zips(snap, {k: v for k, v in c.items() if k != "cities"}):
                city = snap.geo[z].get("city")
                if city:
                    counts[city] = counts.get(city, 0) + 1
            cities = sorted(x for x, k in counts.items() if k >= 3)
            yield ev("Orchestrator", "fan_out", reason="rank cities: one agent run per city with ≥ 3 ZIPs", n_runs=len(cities))
            base = {k: v for k, v in c.items() if k not in ("cities", "zipcodes")}
            for i, city in enumerate(cities):
                yield from collect(_run({**base, "cities": [city]}, snap, seed, i, city))
            items = [{"name": s["label"], "change_pct": s["change_pct"], "start_price": s["start_price"],
                      "end_price": s["end_price"], "end_active": s["end_active"], "confidence": s["confidence"]}
                     for s in facts["runs"] if s[key] is not None]
            scope, window = "the Dallas metro (cities with ≥ 3 ZIPs)", facts["runs"][0]["window"] if facts["runs"] else ["", ""]
            note = "Each city is a full agent run; city figures are active-listing-weighted medians."
        else:
            yield from collect(_run(c, snap, seed, 0, label(c)))
            s = facts["runs"][0] if facts["runs"] else None
            zr = s["zip_rankings"] if s else []
            min_active = 0 if metric == "supply" else 10
            items = [{"name": f"{z['zipcode']} {city_name(z['city'])}".strip(), "change_pct": z["change_pct"],
                      "start_price": z["start_price"], "end_price": z["end_price"], "end_active": z["end_active"]}
                     for z in zr if z["end_active"] >= min_active]
            scope, window = label(c), s["window"] if s else ["", ""]
            note = ("ZIPs with fewer than 10 active listings in the last month are left out "
                    "(a median of a handful of homes swings wildly).") if min_active else None
        items = sorted(items, key=lambda x: x[key] if x[key] is not None else 0, reverse=not asc)[:n]
        facts["ranking"] = {"level": plan["rank_level"], "metric": metric, "order": plan["rank_order"],
                            "scope": scope, "window": window, "items": items, "note": note}
        yield ev("Synthesizer", "ranked_results", level=plan["rank_level"], metric=metric, order=plan["rank_order"], n=len(items))
    elif it == "listings":
        yield ev("DataScout", "queried_listings", tool="ListingQueryTool", scope=label(plan["slices"][0]),
                 bedrooms=plan.get("bedrooms"), status=plan.get("status"))
        facts["listings"] = listing_query(snap, plan["slices"][0], plan)
        yield ev("DataScout", "listings_found", n=facts["listings"]["n"])
    elif it == "macro":
        yield ev("DataScout", "looked_up_macro", tool="MacroLookupTool", indicators=plan["indicators"])
        facts["macro"] = macro_query(snap, plan["slices"][0], plan)
    elif it == "testing":
        req = case_request(q)
        if req:
            yield from collect(run_mr_case(req, facts))
        yield ev("Orchestrator", "read_test_results", source="results/headline_results.json, diagnosis.json")
        facts["testing"] = testing_query(q)

    text, writer = template_answer(plan, facts), "template"
    if llm.provider() and it not in ("help",):
        yield ev("Synthesizer", "wording_answer_with_llm", provider=llm.provider())
        try:
            text, writer = llm_answer(q, plan, facts), f"llm ({llm.provider()})"
        except Exception as e:
            yield ev("Synthesizer", "llm_answer_failed", error=type(e).__name__)
    yield ev("Synthesizer", "answered", writer=writer)
    yield {"type": "answer", "text": text, "writer": writer, "intent": it, "facts": _clean(facts),
           "context": {"intent": it, "base": plan.get("base") or (plan.get("slices") or [{}])[0]}}
    yield {"type": "done", "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
