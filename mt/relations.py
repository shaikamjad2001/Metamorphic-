"""The eight metamorphic relations (design brief, section 4). Each MR states a transformation of the
input (data and/or criteria) and a relation between the source and follow-up TrendOutput."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backend.agents.base import Trace
from backend.agents.orchestrator import Orchestrator
from backend.schemas import RunResult, SearchCriteria
from backend.snapshot import Snapshot, month_add

PRICE_COLS = ("median_price", "average_price", "median_ppsf")
EPS_REL = 1e-5


@dataclass
class Check:
    violated: bool
    max_deviation: float
    detail: dict = field(default_factory=dict)


@dataclass
class MR:
    id: str
    name: str
    family: str
    transformation: str
    relation: str
    subdomain: str
    tolerance: str
    target_fault: str
    transform: Callable[[Snapshot, SearchCriteria, int], tuple[Snapshot, SearchCriteria, dict]]
    check: Callable[[RunResult, RunResult, dict], Check]

    def catalog(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "name", "family", "transformation", "relation",
                                               "subdomain", "tolerance", "target_fault")}


def _series(r: RunResult) -> dict[str, dict]:
    return {s.month: s.model_dump() for s in r.trend.monthly_series}


def _rel(a: Optional[float], b: Optional[float]) -> float:
    """Relative difference; inf when exactly one side is missing."""
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return float("inf")
    return abs(a - b) / max(abs(a), abs(b), 1e-12)


def _resolved_zips(snapshot: Snapshot, c: SearchCriteria) -> list[str]:
    return list(Orchestrator().normalize(c, snapshot, Trace()).zips)


def _scale_prices(snapshot: Snapshot, k: float, unit: Optional[str] = None) -> Snapshot:
    rec = snapshot.records.copy()
    for col in PRICE_COLS:
        rec[col] = rec[col] * k
    return snapshot.with_records(rec, unit)


def _scale_criteria(c: SearchCriteria, k: float, **extra) -> SearchCriteria:
    upd = {f: (getattr(c, f) * k if getattr(c, f) is not None else None) for f in ("min_price", "max_price")}
    return c.model_copy(update={**upd, **extra})


# ---------------------------------------------------------------- MR1 order / relabel invariance
def t_mr1(s, c, seed):
    rng = np.random.default_rng([seed, 1])
    rec = s.records.sample(frac=1.0, random_state=rng.integers(0, 2**31 - 1)).reset_index(drop=True)
    rec["record_id"] = [f"RELABEL-{i:06d}" for i in rng.permutation(len(rec))]
    return s.with_records(rec), c, {}


def c_mr1(src, fol, info):
    a, b = _series(src), _series(fol)
    fields = ("active_count", "median_price", "median_price_per_sqft", "price_q1", "price_q3")
    devs = {f"{m}.{f}": _rel(a[m][f], b[m][f]) for m in a for f in fields}
    devs["cagr"] = _rel(src.trend.annual_cagr_estimate, fol.trend.annual_cagr_estimate)
    worst = max(devs, key=devs.get)
    return Check(devs[worst] > EPS_REL, devs[worst], {"worst_field": worst})


# ---------------------------------------------------------------- MR2 duplicate invariance
def t_mr2(s, c, seed):
    dup = s.records.copy()
    dup["record_id"] = dup["record_id"] + "-DUP"
    return s.with_records(pd.concat([s.records, dup], ignore_index=True)), c, {}


def c_mr2(src, fol, info):
    a, b = _series(src), _series(fol)
    count_bad = [m for m in a if b[m]["active_count"] != 2 * a[m]["active_count"]]
    devs = {f"{m}.{f}": _rel(a[m][f], b[m][f]) for m in a for f in ("median_price", "median_price_per_sqft")}
    worst = max(devs, key=devs.get)
    return Check(bool(count_bad) or devs[worst] > EPS_REL, devs[worst],
                 {"worst_field": worst, "count_not_doubled": count_bad})


# ---------------------------------------------------------------- MR3 currency unit invariance
K_CURRENCY = 0.001


def t_mr3(s, c, seed):
    return _scale_prices(s, K_CURRENCY, "USD_K"), _scale_criteria(c, K_CURRENCY, currency_unit="USD_K"), {"k": K_CURRENCY}


def _scaled_check(src, fol, k, abs_tol):
    a, b = _series(src), _series(fol)
    price_dev, mom_dev, count_bad = {}, {}, []
    for m in a:
        for f in ("median_price", "median_price_per_sqft"):
            x, y = a[m][f], b[m][f]
            price_dev[f"{m}.{f}"] = 0.0 if (x is None and y is None) else (
                float("inf") if (x is None or y is None) else abs(y - k * x))
        x, y = a[m]["mom_pct_price"], b[m]["mom_pct_price"]
        mom_dev[m] = 0.0 if (x is None and y is None) else (float("inf") if (x is None or y is None) else abs(x - y))
        if a[m]["active_count"] != b[m]["active_count"]:
            count_bad.append(m)
    rank_a = [z.zipcode for z in src.trend.zip_rankings]
    rank_b = [z.zipcode for z in fol.trend.zip_rankings]
    wp = max(price_dev, key=price_dev.get)
    wm = max(mom_dev, key=mom_dev.get)
    violated = price_dev[wp] > abs_tol or mom_dev[wm] >= 1e-3 or bool(count_bad) or rank_a != rank_b
    return Check(violated, max(price_dev[wp] / abs_tol, mom_dev[wm] / 1e-3),
                 {"worst_price_field": wp, "worst_price_abs_dev": price_dev[wp], "worst_mom_month": wm,
                  "worst_mom_dev_pp": mom_dev[wm], "count_mismatch": count_bad, "ranking_identical": rank_a == rank_b})


def c_mr3(src, fol, info):
    return _scaled_check(src, fol, K_CURRENCY, 0.05)


# ---------------------------------------------------------------- MR4 additive monotonicity in one month
X_ADD = 15_000.0


def t_mr4(s, c, seed):
    months = [month_add(c.window_end, -i) for i in range(11, -1, -1)]
    rng = np.random.default_rng([seed, 4])
    target = months[int(rng.integers(0, len(months)))]
    rec = s.records.copy()
    hit = rec["month"] == target
    in_scope = hit & rec["zipcode"].isin(_resolved_zips(s, c))
    p = rec.loc[in_scope, "median_price"]
    crossings = lower_crossings = 0
    if c.max_price is not None:
        crossings = int(((p <= c.max_price) & (p + X_ADD > c.max_price)).sum())
    if c.min_price is not None:
        lower_crossings = int(((p < c.min_price) & (p + X_ADD >= c.min_price)).sum())
    rec.loc[hit, "median_price"] += X_ADD
    rec.loc[hit, "average_price"] += X_ADD
    rec.loc[hit, "median_ppsf"] += X_ADD / rec.loc[hit, "median_sqft"]
    return s.with_records(rec), c, {"target_month": target, "x": X_ADD, "upper_band_crossings": crossings,
                                    "lower_band_crossings": lower_crossings}


def c_mr4(src, fol, info):
    a, b = _series(src), _series(fol)
    t = info["target_month"]
    x, y = a[t]["median_price"], b[t]["median_price"]
    delta = None if (x is None or y is None) else y - x
    decreased = delta is None or delta < -1e-6 * max(abs(x or 0), 1)
    others = {m: _rel(a[m]["median_price"], b[m]["median_price"]) for m in a if m != t}
    wo = max(others, key=others.get)
    leaked = others[wo] > EPS_REL
    return Check(decreased or leaked, others[wo] if leaked else (0.0 if not decreased else 1.0),
                 {"target_month": t, "target_delta": delta, "rise_over_x": None if delta is None else delta / info["x"],
                  "target_decreased": decreased, "target_count_delta": b[t]["active_count"] - a[t]["active_count"],
                  "upper_band_crossings": info.get("upper_band_crossings"),
                  "lower_band_crossings": info.get("lower_band_crossings"),
                  "worst_other_month": wo, "worst_other_rel_dev": others[wo],
                  "other_months_changed": [m for m, d in others.items() if d > EPS_REL]})


# ---------------------------------------------------------------- MR5 widening the price band
W_WIDEN = 60_000.0


def t_mr5(s, c, seed):
    lo = None if c.min_price is None else max(0.0, c.min_price - W_WIDEN)
    hi = None if c.max_price is None else c.max_price + W_WIDEN
    return s, c.model_copy(update={"min_price": lo, "max_price": hi}), {}


def c_mr5(src, fol, info):
    a, b = _series(src), _series(fol)
    bad = {m: a[m]["active_count"] - b[m]["active_count"] for m in a if b[m]["active_count"] < a[m]["active_count"]}
    return Check(bool(bad), float(max(bad.values())) if bad else 0.0, {"months_follow_below_source": bad})


# ---------------------------------------------------------------- MR6 geographic restriction
def t_mr6(s, c, seed):
    zips = _resolved_zips(s, c)
    sub = zips[: max(1, len(zips) // 2)]
    return s, c.model_copy(update={"zipcodes": sub}), {"source_zips": len(zips), "subset_zips": len(sub)}


def c_mr6(src, fol, info):
    a, b = _series(src), _series(fol)
    bad = {m: b[m]["active_count"] - a[m]["active_count"] for m in a if b[m]["active_count"] > a[m]["active_count"]}
    return Check(bool(bad), float(max(bad.values())) if bad else 0.0,
                 {"months_follow_above_source": bad, **info})


# ---------------------------------------------------------------- MR7 window slide
def t_mr7(s, c, seed):
    return s, c.model_copy(update={"window_end": month_add(c.window_end, 1)}), {}


def c_mr7(src, fol, info):
    a, b = _series(src), _series(fol)
    overlap = sorted(set(a) & set(b))
    devs = {f"{m}.{f}": _rel(a[m][f], b[m][f]) for m in overlap
            for f in ("median_price", "median_price_per_sqft", "active_count")}
    worst = max(devs, key=devs.get)
    return Check(devs[worst] > EPS_REL, devs[worst],
                 {"overlap_months": len(overlap), "worst_field": worst,
                  "fields_changed": sum(d > EPS_REL for d in devs.values())})


# ---------------------------------------------------------------- MR8 multiplicative price scaling
K_SCALE = 1.25


def t_mr8(s, c, seed):
    return _scale_prices(s, K_SCALE), _scale_criteria(c, K_SCALE), {"k": K_SCALE}


def c_mr8(src, fol, info):
    return _scaled_check(src, fol, K_SCALE, 0.10)


CATALOG: list[MR] = [
    MR("MR1", "Order / relabel invariance", "Invariance",
       "Randomly permute all ZIP-month records and assign fresh record IDs (seeded).",
       "Every monthly active count, median price, median $/sqft, Q1/Q3 and the CAGR are unchanged.",
       "All criteria; all windows.", "relative difference <= 1e-5 (floating-point)",
       "Order-dependent aggregation, unstable sort, index-sensitive grouping, order-dependent bootstrap.",
       t_mr1, c_mr1),
    MR("MR2", "Duplicate invariance", "Invariance",
       "Append an exact copy of every record (2x dataset).",
       "Monthly active counts exactly double; median price and median $/sqft unchanged.",
       "All criteria; all windows.", "counts exact; medians relative difference <= 1e-5",
       "Unweighted averaging, count inflation in estimators, duplicate-key crashes, controllers that read raw row counts.",
       t_mr2, c_mr2),
    MR("MR3", "Currency unit invariance (USD -> USD thousands)", "Invariance",
       "Multiply every price field and the criteria price bounds by 0.001 and switch the unit to USD_K.",
       "Medians scale by exactly 0.001, MoM % changes, counts and the ZIP ranking are identical.",
       "All criteria with price bounds expressed in the same unit.", "scaled prices within 0.05 (follow-up unit); MoM within 1e-3 pp",
       "Hard-coded dollar thresholds, unit-dependent rounding or truncation, non-homogeneous metrics.",
       t_mr3, c_mr3),
    MR("MR4", "Additive monotonicity in one month", "Monotonic",
       "Add $15,000 to the list price of every record in one seeded window month (and $/sqft by 15000/sqft).",
       "That month's median price does not decrease; every other month's median is unchanged.",
       "Windows that contain the target month.", "target delta >= 0; other months relative difference <= 1e-5",
       "Temporal leakage across monthly bins, sign errors, inverted sorting.",
       t_mr4, c_mr4),
    MR("MR5", "Price-band widening monotonicity", "Monotonic",
       "Widen the price band to [Pmin - 60,000, Pmax + 60,000].",
       "Active-listing count of the follow-up is >= the source in every month.",
       "Criteria with a price band.", "exact (integer counts)",
       "Filter inversion, boolean negation errors, lossy joins.",
       t_mr5, c_mr5),
    MR("MR6", "Geographic restriction monotonicity", "Monotonic",
       "Restrict the ZIP set to the first half of the source's resolved ZIPs.",
       "Active-listing count of the follow-up is <= the source in every month.",
       "Criteria resolving to >= 2 ZIPs.", "exact (integer counts)",
       "Spatial boundary leakage, accidental outer joins, filters ignoring the ZIP set.",
       t_mr6, c_mr6),
    MR("MR7", "Window slide consistency", "Directional",
       "Slide the 12-month window forward one month.",
       "The 11 overlapping months have identical median price, median $/sqft and active count.",
       "Window ends with a following month in the snapshot.", "relative difference <= 1e-5",
       "Off-by-one window boundaries, window-dependent processing of individual months.",
       t_mr7, c_mr7),
    MR("MR8", "Multiplicative price scaling", "Directional",
       "Multiply every price field and the price bounds by k = 1.25.",
       "Monthly medians scale by exactly 1.25; MoM % changes, counts and ZIP ranking unchanged.",
       "All criteria.", "scaled prices within $0.10; MoM within 1e-3 pp",
       "Non-linear estimator distortions, improper normalisation in the hedonic adjustment, absolute thresholds.",
       t_mr8, c_mr8),
]


# ---------------------------------------------------------------- refined relations (after diagnosis)
def _pool_radius(r: RunResult) -> int:
    return 2 if "temporal_pool_5" in r.control.refinements else 1 if "temporal_pool_3" in r.control.refinements else 0


def c_mr4r(src, fol, info):
    if (info.get("upper_band_crossings") or 0) + (info.get("lower_band_crossings") or 0) > 0:
        return None
    a, b = _series(src), _series(fol)
    t = info["target_month"]
    radius = max(_pool_radius(src), _pool_radius(fol))
    near = {month_add(t, k) for k in range(-radius, radius + 1)}
    x, y = a[t]["median_price"], b[t]["median_price"]
    decreased = x is None or y is None or (y - x) < -1e-6 * max(abs(x), 1)
    far = {m: _rel(a[m]["median_price"], b[m]["median_price"]) for m in a if m not in near}
    worst = max(far, key=far.get) if far else None
    leaked = bool(far) and far[worst] > EPS_REL
    return Check(decreased or leaked, far[worst] if leaked else (1.0 if decreased else 0.0),
                 {"target_month": t, "pool_radius": radius, "target_decreased": decreased,
                  "months_outside_radius_changed": [m for m, d in far.items() if d > EPS_REL]})


REFINED: list[MR] = [
    MR("MR4R", "Additive monotonicity, refined", "Monotonic",
       "As MR4.",
       "Target month median does not decrease; months outside the follow-up's temporal pooling radius are unchanged.",
       "Base inputs where no in-scope target-month record crosses a price-band bound under +$15,000.",
       "target delta >= 0; months beyond the pooling radius relative difference <= 1e-5",
       "Leakage beyond the declared pooling radius; sign errors.",
       t_mr4, c_mr4r),
]

BY_ID = {m.id: m for m in CATALOG + REFINED}
