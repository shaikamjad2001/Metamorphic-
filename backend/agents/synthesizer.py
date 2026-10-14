"""Agent 5: scores confidence and decides whether to stop or send the trend back for refinement.

Requirement (b), conditional iteration: confidence below target -> a refinement directive goes back
to the Trend Specialist; at or above target (or when the supervisor halts) -> deliver.
Confidence uses a seeded bootstrap, which is where run-to-run (seed) variation enters the system.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from backend import config
from backend.agents.base import Trace
from backend.agents.data_scout import ScanPlan
from backend.agents.orchestrator import NormalizedQuery
from backend.agents.quality_auditor import AuditReport
from backend.agents.trend_specialist import TrendDraft
from backend.schemas import MonthlyStat, TrendOutput, ZipTrend
from backend.stats import bootstrap_weighted_medians

SPARSE_MONTH_HALFWIDTH = 0.5


def fmt_money(x: Optional[float], unit: str) -> str:
    if x is None:
        return "n/a"
    return f"${x:,.2f}K" if unit == "USD_K" else f"${x:,.0f}"


class Synthesizer:
    name = "Synthesizer"

    def evaluate(self, draft: TrendDraft, audit: AuditReport, plan: ScanPlan, seed: int, cycle: int,
                 target: float, trace: Trace) -> dict:
        rng = np.random.default_rng([seed, cycle])
        widths = []
        for m in sorted(draft.samples):
            v, w = draft.samples[m]
            point = next((s["median_price"] for s in draft.series if s["month"] == m), None)
            if v.size < 2 or not point:
                widths.append(SPARSE_MONTH_HALFWIDTH)
                continue
            boots = bootstrap_weighted_medians(v, w, rng, config.BOOTSTRAP_RESAMPLES)
            lo, hi = np.quantile(boots, [0.05, 0.95])
            widths.append(float((hi - lo) / (2 * point)))
        mean_h = float(np.mean(widths)) if widths else SPARSE_MONTH_HALFWIDTH
        stability = float(np.exp(-mean_h / config.STABILITY_SCALE))
        expansion_steps = len(plan.added_zips) / config.SPATIAL_EXPANSION_STEP
        penalty = min(0.5, config.RELAXATION_PENALTY * (plan.relaxation_level + expansion_steps))
        conf = audit.coverage * stability * (1 - penalty)
        if not audit.passed:
            conf = min(conf, config.DEGRADED_CONFIDENCE_CAP)
        out = {"confidence": float(conf), "coverage": audit.coverage, "stability": stability,
               "mean_rel_halfwidth": mean_h, "penalty": penalty, "cycle": cycle}
        trace.log(self.name, "scored_confidence", loop="refinement" if cycle else None, iteration=cycle or None,
                  confidence=round(conf, 4), target=target, coverage=round(audit.coverage, 4),
                  stability=round(stability, 4), mean_rel_ci_halfwidth=round(mean_h, 5),
                  relaxation_penalty=round(penalty, 4), bootstrap_seed=[seed, cycle],
                  verdict="converged" if conf >= target else "below_target")
        return out

    def next_refinement(self, done: list[str], trace: Trace, cycle: int, confidence: float,
                        trim_applicable: bool = True) -> Optional[str]:
        for step in config.REFINEMENT_SEQUENCE:
            if step == "robust_trim" and not trim_applicable:
                continue
            if step not in done and not (step == "temporal_pool_5" and "temporal_pool_3" not in done):
                trace.log(self.name, "requested_refinement", loop="refinement", iteration=cycle,
                          directive=step, confidence=round(confidence, 4))
                return step
        return None

    def finalize(self, q: NormalizedQuery, draft: TrendDraft, score: dict, audit: AuditReport,
                 plan: ScanPlan, trace: Trace) -> tuple[TrendOutput, list[str], str]:
        unit = q.criteria.currency_unit
        caveats = []
        if not audit.passed:
            caveats.append(f"Quality audit failed after relaxation: {len(audit.sparse_months)} month(s) below "
                           f"{config.MIN_ZIPS_PER_MONTH} ZIPs / {config.MIN_ACTIVE_PER_MONTH} active listings "
                           f"({', '.join(audit.sparse_months)}). Confidence capped.")
        if plan.relaxation_level:
            caveats.append(f"Price/size bands were widened by ±{int(plan.relaxation_factor * 100)}% to reach coverage.")
        if plan.added_zips:
            caveats.append(f"Neighbouring ZIPs added for coverage: {', '.join(plan.added_zips)}.")
        if any(r.startswith("temporal_pool") for r in draft.refinements):
            caveats.append("Monthly medians were pooled with neighbouring months to stabilise thin months.")
        if draft.trimmed_records:
            caveats.append(f"{draft.trimmed_records} outlier ZIP-month record(s) excluded from medians ($/sqft MAD rule).")

        trend = TrendOutput(
            window_start=q.months[0], window_end=q.months[-1], currency_unit=unit, method=draft.method,
            monthly_series=[MonthlyStat(**s) for s in draft.series],
            trend_change_pct=draft.change_pct, annual_cagr_estimate=draft.cagr,
            macro_divergence_score=draft.divergence,
            zip_rankings=[ZipTrend(**r) for r in draft.rankings],
            confidence=score["confidence"], quality_audit_passed=audit.passed,
        )
        s0, s1 = draft.series[0], draft.series[-1]
        direction = "rose" if (draft.change_pct or 0) > 0 else "fell" if (draft.change_pct or 0) < 0 else "was flat"
        top = draft.rankings[:3]
        narrative = (
            f"Across {len(q.zips) + len(plan.added_zips)} Dallas-area ZIP codes, the active-listing-weighted median "
            f"list price {direction} from {fmt_money(s0['median_price'], unit)} in {s0['month']} to "
            f"{fmt_money(s1['median_price'], unit)} in {s1['month']}"
            + (f" ({draft.change_pct:+.2f}%, annualised {draft.cagr:+.2f}%)." if draft.change_pct is not None else ".")
            + f" Active listings moved from {s0['active_count']:,} to {s1['active_count']:,}."
            + (f" Median $/sqft went from {s0['median_price_per_sqft']:.0f} to {s1['median_price_per_sqft']:.0f}."
               if unit == "USD" and s0["median_price_per_sqft"] and s1["median_price_per_sqft"] else "")
            + (" Strongest ZIPs: " + ", ".join(f"{r['zipcode']} ({r['change_pct']:+.1f}%)" for r in top) + "."
               if top else "")
            + f" Method: {draft.method.replace('_', ' ')}; confidence {score['confidence']:.2f}."
        )
        trace.log(self.name, "delivered_report", confidence=round(score["confidence"], 4),
                  quality_audit_passed=audit.passed, caveats=len(caveats))
        return trend, caveats, narrative
