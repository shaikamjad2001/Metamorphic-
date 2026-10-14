"""Agent 4: computes the 12-month trend. Its modelling path depends on what upstream agents produced:
the composition signal (Data Scout + Kaggle listings) selects hedonic vs. stratified-median, extreme
sparsity (Quality Auditor) forces the stratified fallback, and the Synthesizer's refinement directives
change the estimator on the next pass."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend import config
from backend.agents.base import Trace
from backend.agents.data_scout import ScanResult
from backend.agents.orchestrator import NormalizedQuery
from backend.agents.quality_auditor import AuditReport
from backend.stats import mad_outliers
from backend.tools import (CagrCalculatorTool, HedonicRegressionTool, MacroDivergenceTool,
                           StratifiedMedianTool)


@dataclass
class TrendDraft:
    method: str
    refinements: list[str]
    series: list[dict]
    samples: dict
    rankings: list[dict]
    change_pct: float | None
    cagr: float | None
    divergence: float | None
    trimmed_records: int = 0
    signals: dict = field(default_factory=dict)


class TrendSpecialist:
    name = "TrendSpecialist"

    def choose_method(self, scan: ScanResult, audit: AuditReport, trace: Trace) -> tuple[str, dict]:
        sq = scan.window_records["median_sqft"].dropna().to_numpy(dtype=float)
        sqft_cv = float(np.std(sq) / np.mean(sq)) if sq.size > 1 and np.mean(sq) > 0 else 0.0
        bed_sigma = float(scan.composition.get("bed_sigma", 0.0))
        signals = {"sqft_cv": round(sqft_cv, 6), "bed_sigma": round(bed_sigma, 6),
                   "thresholds": {"sqft_cv": config.HEDONIC_SQFT_CV_THRESHOLD,
                                  "bed_sigma": config.HEDONIC_BED_SIGMA_THRESHOLD},
                   "extreme_sparsity": audit.extreme_sparsity}
        if audit.extreme_sparsity:
            method, why = "stratified_median", "extreme sparsity: analytical fallback to stratified median"
        elif sqft_cv > config.HEDONIC_SQFT_CV_THRESHOLD or bed_sigma > config.HEDONIC_BED_SIGMA_THRESHOLD:
            method, why = "hedonic", "heterogeneous size / bedroom mix: size-standardise prices"
        else:
            method, why = "stratified_median", "homogeneous mix: plain stratified median"
        trace.log(self.name, "selected_method", method=method, reason=why, **signals)
        return method, signals

    def compute(self, scan: ScanResult, q: NormalizedQuery, method: str, refinements: list[str],
                geo: dict, macro: pd.DataFrame, trace: Trace, cycle: int) -> TrendDraft:
        recs = scan.records
        tools = ([HedonicRegressionTool.name] if method == "hedonic" else []) + [
            StratifiedMedianTool.name, CagrCalculatorTool.name, MacroDivergenceTool.name]
        price = HedonicRegressionTool.run(recs) if method == "hedonic" else recs["median_price"].astype(float)

        est = recs
        trimmed = 0
        if "robust_trim" in refinements:
            keep = pd.Series(True, index=recs.index)
            for _, g in recs.groupby("month"):
                if g["zipcode"].nunique() < config.ROBUST_TRIM_MIN_RECORDS:
                    continue
                out = mad_outliers(g["median_ppsf"].to_numpy(dtype=float), config.ROBUST_TRIM_MAD)
                keep.loc[g.index[out]] = False
            est = recs.loc[keep]
            trimmed = int((~keep).sum())
        pool = 5 if "temporal_pool_5" in refinements else 3 if "temporal_pool_3" in refinements else 1

        months = list(q.months)
        series, samples = StratifiedMedianTool.monthly(est, scan.window_records, months, price, pool=pool)
        rankings = StratifiedMedianTool.zip_rankings(scan.window_records, price, months[0], months[-1], geo)
        p0, p1 = series[0]["median_price"], series[-1]["median_price"]
        change = None if (not p0 or p1 is None) else (p1 / p0 - 1) * 100
        cagr = CagrCalculatorTool.run(p0, p1, len(months))
        div = MacroDivergenceTool.run(series, macro)
        trace.log(self.name, "computed_trend", loop="refinement" if cycle else None, iteration=cycle or None,
                  tools=tools,
                  method=method, refinements=list(refinements), pool_months=pool, trimmed_records=trimmed,
                  trend_change_pct=None if change is None else round(change, 4),
                  cagr_pct=None if cagr is None else round(cagr, 4))
        return TrendDraft(method=method, refinements=list(refinements), series=series, samples=samples,
                          rankings=rankings, change_pct=change, cagr=cagr, divergence=div, trimmed_records=trimmed)
