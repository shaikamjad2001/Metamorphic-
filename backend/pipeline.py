"""Control graph of the multi-agent system (cycles marked with <>):

  Orchestrator -> DataScout -> QualityAuditor --pass--> TrendSpecialist -> Synthesizer --conf>=target--> TrendOutput
                     ^              |                          ^                 |
                     +--<feedback>--+ (relax bands /           +--<refinement>---+ (robust trim / temporal pooling)
                        expand ZIPs)                                                   LoopSupervisor bounds both cycles

`forced` replays a recorded ControlPlan without letting the loops decide ("pinned" mode). The MR
harness uses it as an ablation that separates transformation effects from loop reactions.
"""
from __future__ import annotations

from typing import Optional

from backend import config
from backend.agents import DataScout, LoopSupervisor, Orchestrator, QualityAuditor, Synthesizer, TrendSpecialist
from backend.agents.base import Trace
from backend.agents.data_scout import ScanPlan
from backend.schemas import ControlPlan, RunResult, SearchCriteria
from backend.snapshot import Snapshot, load_snapshot

_orch, _scout, _auditor, _specialist, _synth = Orchestrator(), DataScout(), QualityAuditor(), TrendSpecialist(), Synthesizer()


def run_pipeline(criteria: SearchCriteria, snapshot: Optional[Snapshot] = None, seed: int = 42,
                 forced: Optional[ControlPlan] = None) -> RunResult:
    snapshot = snapshot or load_snapshot()
    trace = Trace()
    sup = LoopSupervisor(trace)
    q = _orch.normalize(criteria, snapshot, trace)
    target = criteria.confidence_target

    # Loop A: Data Scout <-> Quality Auditor (feedback).
    plan = ScanPlan(forced.relaxation_level, list(forced.added_zips)) if forced else ScanPlan()
    iteration = 0
    scan = _scout.scan(snapshot, q, plan, trace, iteration)
    audit = _auditor.audit(scan, q.months, trace, iteration, allow_action=forced is None)
    sup.record_coverage(audit.coverage)
    audit_history = [{"iteration": 0, "coverage": audit.coverage, "action": audit.action}]
    while forced is None and not audit.passed and audit.action:
        if not sup.approve_feedback(iteration + 1):
            break
        iteration += 1
        if audit.action == "relax_bands":
            plan = ScanPlan(plan.relaxation_level + 1, list(plan.added_zips))
        else:
            extra = _scout.nearest_zips(snapshot, scan.zips, config.SPATIAL_EXPANSION_STEP)
            if not extra:
                trace.log(_scout.name, "no_neighbours_left", loop="feedback", iteration=iteration)
                break
            plan = ScanPlan(plan.relaxation_level, list(plan.added_zips) + extra)
        trace.log(_scout.name, "received_feedback", loop="feedback", iteration=iteration, feedback_action=audit.action,
                  new_relaxation_level=plan.relaxation_level, added_zips=list(plan.added_zips))
        scan = _scout.scan(snapshot, q, plan, trace, iteration)
        audit = _auditor.audit(scan, q.months, trace, iteration)
        sup.record_coverage(audit.coverage)
        audit_history.append({"iteration": iteration, "coverage": audit.coverage, "action": audit.action})

    # Method choice depends on upstream outputs (genuine dependency).
    if forced:
        method, signals = forced.method, {"forced": True}
        trace.log(_specialist.name, "selected_method", method=method, reason="pinned control plan")
    else:
        method, signals = _specialist.choose_method(scan, audit, trace)

    # Loop B: Trend Specialist <-> Synthesizer (conditional iteration).
    refinements: list[str] = list(forced.refinements) if forced else []
    cycle = len(refinements)
    draft = _specialist.compute(scan, q, method, refinements, snapshot.geo, scan.macro["metro"], trace, cycle)
    score = _synth.evaluate(draft, audit, plan, seed, cycle, target, trace)
    sup.record_confidence(score["confidence"])
    conf_history = [round(score["confidence"], 6)]
    best = (score["confidence"], draft, score, list(refinements))
    trim_applicable = bool((scan.records.groupby("month")["zipcode"].nunique() >= config.ROBUST_TRIM_MIN_RECORDS).any())
    while forced is None and score["confidence"] < target:
        if not sup.approve_refinement(cycle + 1):
            break
        step = _synth.next_refinement(refinements, trace, cycle + 1, score["confidence"], trim_applicable)
        if step is None:
            trace.log(_synth.name, "refinements_exhausted", loop="refinement", iteration=cycle + 1,
                      confidence=round(score["confidence"], 4))
            break
        refinements.append(step)
        cycle += 1
        draft = _specialist.compute(scan, q, method, refinements, snapshot.geo, scan.macro["metro"], trace, cycle)
        score = _synth.evaluate(draft, audit, plan, seed, cycle, target, trace)
        sup.record_confidence(score["confidence"])
        conf_history.append(round(score["confidence"], 6))
        if score["confidence"] > best[0]:
            best = (score["confidence"], draft, score, list(refinements))

    attempted = list(refinements)
    if best[0] > score["confidence"]:
        _, draft, score, refinements = best
        trace.log(_synth.name, "kept_best_draft", refinements=refinements, confidence=round(score["confidence"], 4))

    trend, caveats, narrative = _synth.finalize(q, draft, score, audit, plan, trace)
    control = ControlPlan(relaxation_level=plan.relaxation_level, relaxation_factor=plan.relaxation_factor,
                          added_zips=list(plan.added_zips), method=method, refinements=list(refinements))
    return RunResult(
        criteria=criteria, seed=seed, trend=trend, control=control, events=trace.events, caveats=caveats,
        narrative=narrative,
        diagnostics={
            "pinned": forced is not None,
            "feedback_cycles": iteration,
            "refinement_cycles": len(attempted) if not forced else 0,
            "refinements_attempted": attempted,
            "audit_history": audit_history,
            "confidence_history": conf_history,
            "confidence_components": score,
            "method_signals": signals,
            "composition": {k: v for k, v in scan.composition.items() if k != "zip_median_beds"},
            "zips_in_scope": scan.zips,
            "bands_used": scan.bands.__dict__,
            "supervisor_halts": sup.halts,
            "runtime_ms": round(trace.elapsed_s() * 1000, 2),
        },
    )
