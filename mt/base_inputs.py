"""Generates the 32 distinct base inputs (criteria slices) with a fixed generator seed.

Every slice carries a price band, so the band-widening MR is never a no-op, and resolves to at
least two ZIP codes, so the ZIP-subset MR has a proper subset. Window ends stop at 2026-08 so the
window-slide MR always has a following month in the snapshot.
"""
from __future__ import annotations

import json
import os

import numpy as np

from backend.schemas import SearchCriteria
from backend.snapshot import Snapshot, load_snapshot, window_months

GENERATOR_SEED = 20261016
N_BASE = 32
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_inputs.json")

CITIES = ["Dallas", "Plano", "Irving", "Garland", "Frisco", "Mckinney", "Richardson", "Mesquite",
          "Carrollton", "Grand Prairie", "Allen", "Rowlett"]
TIERS = ["Entry", "Value", "Mid-Market", "Upper", "Luxury"]
CORE10 = ["75201", "75202", "75204", "75205", "75206", "75209", "75214", "75219", "75225", "75230"]


def _round5k(x: float) -> float:
    return float(round(x / 5000.0) * 5000)


def _resolve(s: Snapshot, kind: str, value) -> list[str]:
    if kind == "city":
        return [z for z, g in s.geo.items() if (g.get("city") or "").lower() == value.lower()]
    if kind == "tier":
        return [z for z, g in s.geo.items() if g.get("price_tier") == value]
    return list(value)


def generate(s: Snapshot | None = None) -> list[dict]:
    s = s or load_snapshot()
    rng = np.random.default_rng(GENERATOR_SEED)
    ends = [m for m in s.months if "2023-12" <= m <= "2026-08"]
    specs: list[tuple[str, object]] = []
    specs += [("tier", t) for t in TIERS]
    specs += [("city", c) for c in CITIES]
    specs += [("zips", CORE10), ("zips", CORE10[:5]), ("zips", CORE10[5:])]
    zips_all = s.zipcodes
    while len(specs) < N_BASE - 2:
        k = int(rng.integers(3, 16))
        specs.append(("zips", sorted(rng.choice(zips_all, size=k, replace=False).tolist())))
    specs += [("metro", None), ("metro", None)]

    out = []
    for i, (kind, value) in enumerate(specs):
        end = str(ends[int(rng.integers(0, len(ends)))])
        zips = zips_all if kind == "metro" else _resolve(s, kind, value)
        months = window_months(end)
        prices = s.records[s.records["zipcode"].isin(zips) & s.records["month"].isin(months)]["median_price"]
        lo_q = float(rng.choice([0.0, 0.05, 0.1, 0.2, 0.3]))
        hi_q = float(rng.choice([0.6, 0.7, 0.8, 0.9, 0.95, 1.0]))
        crit = {"window_end": end,
                "min_price": _round5k(prices.quantile(lo_q)),
                "max_price": _round5k(prices.quantile(hi_q))}
        if kind == "city":
            crit["cities"] = [value]
        elif kind == "tier":
            crit["tiers"] = [value]
        elif kind == "zips":
            crit["zipcodes"] = list(value)
        if rng.random() < 0.3:
            sq = s.records[s.records["zipcode"].isin(zips) & s.records["month"].isin(months)]["median_sqft"]
            crit["min_sqft"] = float(round(sq.quantile(0.05), -1))
            crit["max_sqft"] = float(round(sq.quantile(0.95), -1))
        label = f"B{i + 1:02d}-{kind}-" + (value if isinstance(value, str) else (f"{len(value)}zips" if value else "all"))
        crit["label"] = label
        SearchCriteria(**crit)
        out.append(crit)
    return out


def load_base_inputs() -> list[SearchCriteria]:
    if not os.path.exists(PATH):
        write()
    with open(PATH) as f:
        return [SearchCriteria(**c) for c in json.load(f)["base_inputs"]]


def write() -> None:
    data = {"generator_seed": GENERATOR_SEED, "n": N_BASE, "base_inputs": generate()}
    with open(PATH, "w") as f:
        json.dump(data, f, indent=1)


if __name__ == "__main__":
    write()
    print(f"wrote {PATH}")
