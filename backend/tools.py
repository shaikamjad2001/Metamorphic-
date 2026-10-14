"""The six domain tools agents delegate to (design brief, section 3.2). Pure functions over DataFrames."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from backend import config
from backend.snapshot import Snapshot
from backend.stats import weighted_median, weighted_quantile


@dataclass(frozen=True)
class Bands:
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_sqft: Optional[float] = None
    max_sqft: Optional[float] = None

    def relaxed(self, r: float) -> "Bands":
        """Widen every bound by a relative factor r (lower bounds shrink, upper bounds grow)."""
        lo = lambda x: None if x is None else x * (1 - r)
        hi = lambda x: None if x is None else x * (1 + r)
        return Bands(lo(self.min_price), hi(self.max_price), lo(self.min_sqft), hi(self.max_sqft))

    @property
    def is_unbounded(self) -> bool:
        return all(v is None for v in (self.min_price, self.max_price, self.min_sqft, self.max_sqft))


class ListingFilterTool:
    """Slices ZIP-month records by ZIP set, months and (relaxed) price / size bands."""

    name = "ListingFilterTool"

    @staticmethod
    def run(snapshot: Snapshot, zips: list[str], months: list[str], bands: Bands) -> pd.DataFrame:
        rec = snapshot.records
        floor = config.MIN_VALID_PRICE_USD * config.CURRENCY_FACTORS[snapshot.currency_unit]
        m = rec["zipcode"].isin(zips) & rec["month"].isin(months) & (rec["median_price"] >= floor)
        if bands.min_price is not None:
            m &= rec["median_price"] >= bands.min_price
        if bands.max_price is not None:
            m &= rec["median_price"] <= bands.max_price
        if bands.min_sqft is not None:
            m &= rec["median_sqft"] >= bands.min_sqft
        if bands.max_sqft is not None:
            m &= rec["median_sqft"] <= bands.max_sqft
        return rec.loc[m]

    @staticmethod
    def excluded_by_bands(snapshot: Snapshot, zips: list[str], months: list[str], bands: Bands) -> int:
        """How many in-scope records the bands removed: tells the auditor whether relaxing bands can help."""
        everything = ListingFilterTool.run(snapshot, zips, months, Bands())
        kept = ListingFilterTool.run(snapshot, zips, months, bands)
        return len(everything) - len(kept)


class MacroLookupTool:
    """Attaches Zillow ZHVI, FRED (Realtor.com MSA series, 30y mortgage) and FHFA HPI for the window."""

    name = "MacroLookupTool"

    @staticmethod
    def run(snapshot: Snapshot, months: list[str], zips: list[str]) -> dict:
        macro = snapshot.macro[snapshot.macro["month"].isin(months)].sort_values("month")
        zz = snapshot.zip_zhvi[snapshot.zip_zhvi["zipcode"].isin(zips) & snapshot.zip_zhvi["month"].isin(months)]
        return {"metro": macro.reset_index(drop=True), "zip_zhvi": zz.reset_index(drop=True)}


class CompositionProfileTool:
    """Listing-level composition from the real Kaggle listings in the selected ZIPs."""

    name = "CompositionProfileTool"

    @staticmethod
    def run(snapshot: Snapshot, zips: list[str]) -> dict:
        lst = snapshot.listings[snapshot.listings["zipcode"].isin(zips)]
        valid = lst[(lst["bedrooms"] > 0) & (lst["sqft"] > 0)]
        if valid.empty:
            return {"n_listings": 0, "bed_sigma": 0.0, "listing_sqft_cv": 0.0, "median_beds": None,
                    "median_sqft": None, "zip_median_beds": {}}
        per_zip = valid.groupby("zipcode")["bedrooms"].median()
        sq = valid["sqft"].to_numpy(dtype=float)
        return {
            "n_listings": int(len(valid)),
            "bed_sigma": float(np.std(per_zip.to_numpy(dtype=float))) if len(per_zip) > 1 else 0.0,
            "listing_sqft_cv": float(np.std(sq) / np.mean(sq)),
            "median_beds": float(valid["bedrooms"].median()),
            "median_sqft": float(valid["sqft"].median()),
            "zip_median_beds": {k: float(v) for k, v in per_zip.items()},
        }


class HedonicRegressionTool:
    """Size-standardises each ZIP-month median price to an 1,800 sqft baseline:
    P_adj = P * (1800 / sqft) ** 0.75."""

    name = "HedonicRegressionTool"

    @staticmethod
    def run(records: pd.DataFrame) -> pd.Series:
        sqft = records["median_sqft"].astype(float)
        factor = (config.HEDONIC_BASE_SQFT / sqft) ** config.HEDONIC_ELASTICITY
        return (records["median_price"] * factor).where(sqft > 0, records["median_price"])


class StratifiedMedianTool:
    """Per-month statistics with each ZIP-month record as one stratum weighted by its active listings."""

    name = "StratifiedMedianTool"

    @staticmethod
    def monthly(est_records: pd.DataFrame, count_records: pd.DataFrame, months: list[str],
                price: pd.Series, pool: int = 1) -> tuple[list[dict], dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Medians come from est_records (possibly trimmed / pooled); counts always come from
        count_records (everything the scan matched). pool=3/5 pools neighbouring months' records,
        centred on the target month (used only by the refinement cycle).

        Returns the monthly rows and, per month, the (values, weights) sample behind the median."""
        price = price.reindex(est_records.index)
        by_month = {m: est_records.index[est_records["month"] == m] for m in sorted(est_records["month"].unique())}
        all_months = sorted(by_month)
        half = pool // 2
        out, samples = [], {}
        prev = None
        for m in months:
            if pool > 1 and m in all_months:
                pos = all_months.index(m)
                parts = [by_month[x] for x in all_months[max(0, pos - half): pos + half + 1]]
                pidx = parts[0].append(parts[1:]) if len(parts) > 1 else parts[0]
            else:
                pidx = by_month.get(m, pd.Index([]))
            cur = count_records[count_records["month"] == m]
            pw = est_records.loc[pidx, "active_count"].to_numpy(dtype=float)
            pv = price.loc[pidx].to_numpy(dtype=float)
            samples[m] = (pv, pw)
            med = weighted_median(pv, pw)
            ppsf = weighted_median(est_records.loc[pidx, "median_ppsf"].to_numpy(dtype=float), pw)
            dom = weighted_median(cur["median_dom"].to_numpy(dtype=float), cur["active_count"].to_numpy(dtype=float))
            mom = None if (prev is None or med is None or prev == 0) else (med / prev - 1) * 100
            out.append({
                "month": m,
                "active_count": int(cur["active_count"].sum()),
                "n_zips": int(cur["zipcode"].nunique()),
                "median_price": med,
                "median_price_per_sqft": ppsf,
                "price_q1": weighted_quantile(pv, pw, 0.25),
                "price_q3": weighted_quantile(pv, pw, 0.75),
                "new_listings": int(cur["new_listings"].sum()),
                "median_dom": dom,
                "mom_pct_price": mom,
            })
            prev = med
        return out, samples

    @staticmethod
    def zip_rankings(records: pd.DataFrame, price: pd.Series, start: str, end: str, geo: dict) -> list[dict]:
        price = price.reindex(records.index)
        s = records.assign(_p=price)

        def per_zip(month: str) -> dict[str, tuple[float, int]]:
            sub = s[s["month"] == month]
            return {z: (weighted_median(g["_p"].to_numpy(dtype=float), g["active_count"].to_numpy(dtype=float)),
                        int(g["active_count"].sum()))
                    for z, g in sub.groupby("zipcode")}

        a, b = per_zip(start), per_zip(end)
        rows = []
        for z in sorted(set(a) & set(b)):
            p0, p1 = a[z][0], b[z][0]
            if p0 and p1 is not None and p0 > 0:
                rows.append({"zipcode": z, "city": geo.get(z, {}).get("city"), "start_price": p0,
                             "end_price": p1, "change_pct": (p1 / p0 - 1) * 100, "end_active": b[z][1]})
        rows.sort(key=lambda r: (-round(r["change_pct"], 9), r["zipcode"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return rows


class CagrCalculatorTool:
    """CAGR = (P_end / P_start) ** (12 / (n - 1)) - 1, in percent."""

    name = "CagrCalculatorTool"

    @staticmethod
    def run(p_start: Optional[float], p_end: Optional[float], n_months: int) -> Optional[float]:
        if not p_start or p_end is None or n_months < 2 or p_start <= 0 or p_end <= 0:
            return None
        return ((p_end / p_start) ** (12 / (n_months - 1)) - 1) * 100


class MacroDivergenceTool:
    """Mean absolute percentage deviation between the trend and Zillow ZHVI, both rebased to 100 at the
    first month present in both. Rebasing makes the score independent of currency unit and price level."""

    name = "MacroDivergenceTool"

    @staticmethod
    def run(series: list[dict], macro: pd.DataFrame) -> Optional[float]:
        zhvi = dict(zip(macro["month"], macro["zhvi_metro"]))
        pairs = [(s["median_price"], zhvi.get(s["month"])) for s in series]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None and not np.isnan(b)]
        if len(pairs) < 2:
            return None
        a0, b0 = pairs[0]
        devs = [abs((a / a0) - (b / b0)) / (b / b0) * 100 for a, b in pairs]
        return float(np.mean(devs))
