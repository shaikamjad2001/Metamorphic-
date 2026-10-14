"""Agent 3: checks per-month sample adequacy and, when it fails, sends work back to the Data Scout.

Requirement (a), feedback loop: the auditor is downstream of the scout and returns a *typed* action.
Requirement (c), genuine dependency: the action it picks (relax the bands vs. expand the ZIP set)
changes which strategy the scout executes next, not just the data it receives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from backend import config
from backend.agents.base import Trace
from backend.agents.data_scout import ScanResult

Action = Optional[Literal["relax_bands", "expand_spatial"]]


@dataclass
class AuditReport:
    passed: bool
    coverage: float
    per_month: dict[str, dict]
    sparse_months: list[str]
    action: Action = None
    reason: str = ""
    min_zips_seen: int = 0
    extreme_sparsity: bool = False
    notes: list[str] = field(default_factory=list)


class QualityAuditor:
    name = "QualityAuditor"

    def audit(self, scan: ScanResult, months: tuple[str, ...], trace: Trace, iteration: int,
              allow_action: bool = True) -> AuditReport:
        w = scan.window_records
        per_month = {}
        for m in months:
            sub = w[w["month"] == m]
            per_month[m] = {"n_zips": int(sub["zipcode"].nunique()), "active": int(sub["active_count"].sum())}
        sparse = [m for m, v in per_month.items()
                  if v["n_zips"] < config.MIN_ZIPS_PER_MONTH or v["active"] < config.MIN_ACTIVE_PER_MONTH]
        coverage = 1 - len(sparse) / len(months)
        min_zips = min(v["n_zips"] for v in per_month.values())
        rep = AuditReport(passed=not sparse, coverage=coverage, per_month=per_month, sparse_months=sparse,
                          min_zips_seen=min_zips, extreme_sparsity=min_zips <= config.EXTREME_SPARSITY_ZIPS)

        if sparse and allow_action:
            can_relax = (not scan.bands.is_unbounded and scan.excluded_by_bands > 0
                         and scan.plan.relaxation_level < len(config.RELAXATION_SCHEDULE))
            zip_starved = len(scan.zips) < config.MIN_ZIPS_PER_MONTH
            if can_relax and not zip_starved:
                rep.action = "relax_bands"
                rep.reason = (f"{len(sparse)} sparse month(s) and the bands exclude {scan.excluded_by_bands} "
                              f"in-scope records: widen bands")
            else:
                rep.action = "expand_spatial"
                rep.reason = ("too few ZIP submarkets in scope" if zip_starved
                              else "bands are not the bottleneck: add neighbouring ZIPs")

        trace.log(self.name, "audit_passed" if rep.passed else "audit_failed",
                  loop="feedback" if iteration else None, iteration=iteration,
                  coverage=round(coverage, 4), sparse_months=sparse, min_zips_per_month=min_zips,
                  thresholds={"min_zips": config.MIN_ZIPS_PER_MONTH, "min_active": config.MIN_ACTIVE_PER_MONTH},
                  next_action=rep.action, reason=rep.reason)
        return rep
