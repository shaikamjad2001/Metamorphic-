"""FastAPI service for the UI. Run:  python start.py   (or uvicorn backend.api:app --port 8000)"""
from __future__ import annotations

import json
import math
import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from backend import config, llm
from backend.agents.orchestrator import CriteriaError
from backend.nl_parser import parse_rules
from backend.pipeline import run_pipeline
from backend.schemas import SearchCriteria
from backend.snapshot import load_snapshot

app = FastAPI(title="Dallas Housing Trends - Multi-Agent System", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _clean(obj):
    """JSON-safe: NaN/inf -> None."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _read_json(name: str):
    path = os.path.join(config.RESULTS_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.provider()}


@app.get("/api/meta")
def meta():
    s = load_snapshot()
    cities: dict[str, int] = {}
    for g in s.geo.values():
        if g.get("city"):
            cities[g["city"]] = cities.get(g["city"], 0) + 1
    m = s.manifest
    return _clean({
        "months": s.months,
        "default_window_end": config.DEFAULT_WINDOW_END,
        "zips": list(s.geo.values()),
        "cities": sorted(({"city": c, "n_zips": n} for c, n in cities.items()), key=lambda x: (-x["n_zips"], x["city"])),
        "tiers": ["Entry", "Value", "Mid-Market", "Upper", "Luxury"],
        "seeds": list(config.SEEDS),
        "n_records": int(len(s.records)),
        "n_listings": int(len(s.listings)),
        "manifest": {k: m.get(k) for k in ("snapshot_version", "all_values_real", "synthetic_or_imputed_values",
                                           "months", "n_zipcodes", "sources", "snapshot_sha256")},
        "retrieved_at": (m.get("raw_download_manifest") or {}).get("retrieved_at_utc"),
        "thresholds": {"min_zips_per_month": config.MIN_ZIPS_PER_MONTH, "min_active_per_month": config.MIN_ACTIVE_PER_MONTH,
                       "relaxation_schedule": config.RELAXATION_SCHEDULE, "confidence_target": config.CONFIDENCE_TARGET,
                       "max_feedback_cycles": config.MAX_FEEDBACK_CYCLES,
                       "max_refinement_cycles": config.MAX_REFINEMENT_CYCLES},
        "llm": llm.provider(),
    })


class AnalyzeRequest(BaseModel):
    criteria: SearchCriteria
    seed: int = 42


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    s = load_snapshot()
    try:
        r = run_pipeline(req.criteria, s, req.seed)
    except CriteriaError as e:
        raise HTTPException(422, str(e))
    t = r.trend
    rank = {z.zipcode: z for z in t.zip_rankings}
    scope = set(r.diagnostics["zips_in_scope"])
    added = set(r.control.added_zips)
    zips = []
    for z, g in s.geo.items():
        zt = rank.get(z)
        zips.append({**g, "in_scope": z in scope, "added": z in added,
                     "change_pct": zt.change_pct if zt else None, "end_price": zt.end_price if zt else None,
                     "end_active": zt.end_active if zt else None, "rank": zt.rank if zt else None})
    macro = s.macro.set_index("month")
    first = next((m for m in t.monthly_series if m.median_price), None)
    bench, z0, f0 = [], None, None
    for m in t.monthly_series:
        row = macro.loc[m.month] if m.month in macro.index else None
        zhvi = None if row is None or math.isnan(row["zhvi_metro"]) else float(row["zhvi_metro"])
        fred = None if row is None or math.isnan(row["fred_median_listing_price"]) else float(row["fred_median_listing_price"])
        z0 = z0 or zhvi
        f0 = f0 or fred
        bench.append({
            "month": m.month,
            "trend_index": (m.median_price / first.median_price * 100) if (first and m.median_price) else None,
            "zhvi_index": (zhvi / z0 * 100) if (zhvi and z0) else None,
            "fred_index": (fred / f0 * 100) if (fred and f0) else None,
            "zhvi_metro": zhvi, "fred_median_listing_price": fred,
            "fred_active_listing_count": None if row is None else float(row["fred_active_listing_count"]),
            "mortgage_rate_30y": None if row is None else float(row["mortgage_rate_30y"]),
        })
    return _clean({"result": r.model_dump(), "zips": zips, "benchmark": bench})


class ParseRequest(BaseModel):
    query: str
    use_llm: bool = True


@app.post("/api/parse")
def parse(req: ParseRequest):
    s = load_snapshot()
    crit, notes = parse_rules(req.query, s)
    parser = "rules"
    if req.use_llm and llm.provider():
        try:
            got = {k: v for k, v in (llm.parse_with_llm(req.query) or {}).items() if v not in (None, [], "")}
            merged = {**got, **crit}
            SearchCriteria(**merged)
            crit, parser = merged, f"rules + {llm.provider()}"
        except (ValidationError, Exception) as e:  # LLM is optional; never fail the request on it
            notes.append(f"LLM parse skipped: {type(e).__name__}")
    try:
        SearchCriteria(**crit)
    except ValidationError as e:
        raise HTTPException(422, str(e))
    return {"criteria": crit, "parser": parser, "notes": notes}


@app.get("/api/listings")
def listings(zipcodes: Optional[str] = None, status: Optional[str] = None, limit: int = Query(200, le=2000)):
    s = load_snapshot()
    df = s.listings
    if zipcodes:
        df = df[df["zipcode"].isin([z.strip() for z in zipcodes.split(",")])]
    if status:
        df = df[df["status"] == status]
    summary = {
        "n": int(len(df)),
        "by_status": {k: int(v) for k, v in df["status"].value_counts().items()},
        "median_price": float(df["price"].median()) if len(df) else None,
        "median_sqft": float(df["sqft"].median()) if df["sqft"].notna().any() else None,
        "median_ppsf": float(df["price_per_sqft"].median()) if df["price_per_sqft"].notna().any() else None,
        "beds": {str(int(k)): int(v) for k, v in df["bedrooms"].dropna().clip(upper=6).value_counts().sort_index().items()},
    }
    rows = df.sort_values("listing_id").head(limit).to_dict(orient="records")
    return _clean({"summary": summary, "rows": rows})


@app.get("/api/macro")
def macro():
    return _clean(load_snapshot().macro.to_dict(orient="records"))


@app.get("/api/mt/catalog")
def mt_catalog():
    from mt.base_inputs import load_base_inputs
    from mt.relations import CATALOG, REFINED
    return {"relations": [m.catalog() for m in CATALOG + REFINED],
            "base_inputs": [b.model_dump(exclude_none=True) for b in load_base_inputs()],
            "seeds": list(config.SEEDS)}


@app.get("/api/mt/results")
def mt_results():
    res = _read_json("headline_results.json")
    if res is None:
        raise HTTPException(404, "run `python run_headline_results.py` first")
    history = []
    hdir = os.path.join(config.RESULTS_DIR, "history")
    if os.path.isdir(hdir):
        for name in sorted(os.listdir(hdir)):
            p = os.path.join(hdir, name, "headline_results.json")
            if os.path.exists(p):
                with open(p) as f:
                    h = json.load(f)
                history.append({"stage": name, "natural": h["results"].get("natural", [])})
    return _clean({"headline": res, "diagnosis": _read_json("diagnosis.json"), "history": history})


@app.get("/api/mt/cases")
def mt_cases(mr: str):
    from backend.chat import recorded_cases
    keep = ("base_idx", "base", "seed", "mode", "violated", "applicable", "path_diverged", "max_deviation", "error")
    return _clean([{k: r.get(k) for k in keep} for r in recorded_cases(mr)])


class CaseRequest(BaseModel):
    mr: str
    base_idx: int = 0
    seed: int = 42
    mode: Literal["natural", "pinned"] = "natural"


@app.post("/api/mt/run")
def mt_run(req: CaseRequest):
    from mt.harness import explain_case
    from mt.relations import BY_ID
    if req.mr not in BY_ID:
        raise HTTPException(404, f"unknown MR {req.mr}")
    return _clean(explain_case(req.mr, req.base_idx, req.seed, req.mode))


class ChatRequest(BaseModel):
    question: str
    seed: int = 42
    context: Optional[dict] = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Streams newline-delimited JSON events: agent steps as they happen, then the answer."""
    from backend.chat import chat_stream

    def gen():
        try:
            for item in chat_stream(req.question, req.seed, req.context):
                yield json.dumps(_clean(item), default=str) + "\n"
        except Exception as e:  # surface failures to the UI instead of a broken stream
            yield json.dumps({"type": "error", "text": f"{type(e).__name__}: {e}"}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/api/trace")
def trace():
    t = _read_json("loop_trace.json")
    if t is None:
        raise HTTPException(404, "run `python scripts/make_loop_trace.py` first")
    return _clean(t)


DIST = os.path.join(config.ROOT, "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
