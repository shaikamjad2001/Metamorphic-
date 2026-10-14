"""Natural-language query -> SearchCriteria. Deterministic rules first; an optional local/remote LLM can
fill gaps (backend/llm.py). The parsed criteria are always validated by the SearchCriteria schema."""
from __future__ import annotations

import re
from typing import Optional

from backend.snapshot import Snapshot

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
TIER_WORDS = {"entry": "Entry", "starter": "Entry", "affordable": "Value", "value": "Value", "mid": "Mid-Market",
              "mid-market": "Mid-Market", "upper": "Upper", "upscale": "Upper", "luxury": "Luxury", "premium": "Luxury"}
NUM = r"\$?\s*(\d+(?:\.\d+)?)\s*(k|m|mm|million|thousand)?"


def _money(num: str, suffix: Optional[str]) -> float:
    x = float(num)
    s = (suffix or "").lower()
    if s in ("k", "thousand"):
        x *= 1_000
    elif s in ("m", "mm", "million"):
        x *= 1_000_000
    elif x < 10_000:
        x *= 1_000
    return x


def parse_rules(query: str, snapshot: Snapshot) -> tuple[dict, list[str]]:
    q = query.lower()
    out: dict = {}
    notes: list[str] = []

    zips = sorted(set(re.findall(r"\b75\d{3}\b", q)))
    if zips:
        out["zipcodes"] = zips
    cities = sorted({(g.get("city") or "") for g in snapshot.geo.values()} - {""}, key=len, reverse=True)
    found = [c for c in cities if re.search(rf"\b{re.escape(c.lower())}\b", q)]
    if found and not zips:
        out["cities"] = found
    tiers = sorted({t for w, t in TIER_WORDS.items() if re.search(rf"\b{w}\b", q)})
    if tiers:
        out["tiers"] = tiers

    sq = re.search(r"(\d{3,5})\s*(?:-|to|and)\s*(\d{3,5})\s*(?:sq\.?\s*ft|sqft|square feet)", q)
    if sq:
        out["min_sqft"], out["max_sqft"] = float(sq.group(1)), float(sq.group(2))
        q = q.replace(sq.group(0), " ")
    m = re.search(rf"between\s+{NUM}\s+(?:and|to|-)\s+{NUM}", q) or re.search(rf"{NUM}\s*(?:-|to)\s*{NUM}", q)
    if m:
        out["min_price"], out["max_price"] = _money(m.group(1), m.group(2)), _money(m.group(3), m.group(4))
    else:
        hi = re.search(rf"(?:under|below|less than|max(?:imum)?|up to|<)\s*{NUM}", q)
        lo = re.search(rf"(?:over|above|more than|min(?:imum)?|at least|>)\s*{NUM}", q)
        if hi:
            out["max_price"] = _money(hi.group(1), hi.group(2))
        if lo:
            out["min_price"] = _money(lo.group(1), lo.group(2))

    months = snapshot.months
    iso = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q)
    named = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", q)
    if iso:
        out["window_end"] = f"{iso.group(1)}-{iso.group(2)}"
    elif named:
        out["window_end"] = f"{named.group(2)}-{MONTHS[named.group(1)]:02d}"
    else:
        yr = re.search(r"\b(20\d{2})\b", q)
        if yr:
            out["window_end"] = f"{yr.group(1)}-12"
    if "window_end" in out and out["window_end"] > months[-1]:
        notes.append(f"window end {out['window_end']} is after the snapshot; using {months[-1]}")
        out["window_end"] = months[-1]
    if not out:
        notes.append("no filters recognised; analysing the whole Dallas metro for the latest 12 months")
    return out, notes
