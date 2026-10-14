"""Metamorphic harness: transform -> re-run -> compare, over base inputs x seeds, with Wilson 95% CIs.

Modes
  natural  the follow-up run makes its own control decisions (the system as deployed). Headline table.
  pinned   the follow-up replays the source run's ControlPlan (relaxation, added ZIPs, method,
           refinements). Ablation: isolates the transformation from the loops' reaction to it.
"""
from __future__ import annotations

import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Iterable

from backend import config
from backend.pipeline import run_pipeline
from backend.snapshot import load_snapshot
from backend.stats import wilson_interval
from mt.base_inputs import load_base_inputs
from mt.relations import BY_ID, CATALOG, REFINED

_STATE: dict = {}


def _init() -> None:
    _STATE["snapshot"] = load_snapshot()
    _STATE["bases"] = load_base_inputs()


def _fingerprint(r) -> dict:
    c = r.control
    return {"relaxation_level": c.relaxation_level, "added_zips": c.added_zips, "method": c.method,
            "refinements": c.refinements}


def run_case(mr_id: str, base_idx: int, seed: int, mode: str) -> dict:
    if not _STATE:
        _init()
    snap, base = _STATE["snapshot"], _STATE["bases"][base_idx]
    mr = BY_ID[mr_id]
    rec = {"mr": mr_id, "base_idx": base_idx, "base": base.label, "seed": seed, "mode": mode}
    try:
        src = run_pipeline(base, snap, seed)
        snap2, crit2, info = mr.transform(snap, base, seed)
        rec["transform_info"] = info
        rec["source"] = {**_fingerprint(src), "confidence": src.trend.confidence,
                         "audit_passed": src.trend.quality_audit_passed}
    except Exception as exc:  # the source run itself failing is a harness problem, not an MR verdict
        rec.update(violated=None, error=f"source: {exc!r}", trace=traceback.format_exc(limit=3))
        return rec
    try:
        forced = src.control if mode == "pinned" else None
        fol = run_pipeline(crit2, snap2, seed, forced=forced)
        chk = mr.check(src, fol, info)
        rec["follow"] = {**_fingerprint(fol), "confidence": fol.trend.confidence,
                         "audit_passed": fol.trend.quality_audit_passed}
        rec["path_diverged"] = _fingerprint(src) != _fingerprint(fol)
        if chk is None:
            rec.update(violated=None, applicable=False, error=None)
            return rec
        rec.update(violated=bool(chk.violated), applicable=True, max_deviation=chk.max_deviation,
                   detail=chk.detail, error=None)
    except Exception as exc:
        rec.update(violated=True, error=f"follow-up: {exc!r}", trace=traceback.format_exc(limit=4),
                   max_deviation=float("inf"), path_diverged=None)
    return rec


def explain_case(mr_id: str, base_idx: int, seed: int, mode: str = "natural") -> dict:
    """One MR execution with both full outputs, for the UI's side-by-side view."""
    if not _STATE:
        _init()
    snap, base = _STATE["snapshot"], _STATE["bases"][base_idx]
    mr = BY_ID[mr_id]
    src = run_pipeline(base, snap, seed)
    snap2, crit2, info = mr.transform(snap, base, seed)
    fol = run_pipeline(crit2, snap2, seed, forced=src.control if mode == "pinned" else None)
    chk = mr.check(src, fol, info)
    side = lambda r: {"series": [m.model_dump() for m in r.trend.monthly_series], "control": r.control.model_dump(),
                      "confidence": r.trend.confidence, "method": r.trend.method,
                      "trend_change_pct": r.trend.trend_change_pct, "currency_unit": r.trend.currency_unit,
                      "events": [e.model_dump() for e in r.events]}
    return {"mr": mr.catalog(), "mode": mode, "seed": seed, "base_idx": base_idx,
            "source_criteria": base.model_dump(exclude_none=True), "follow_criteria": crit2.model_dump(exclude_none=True),
            "transform_info": info, "applicable": chk is not None,
            "violated": None if chk is None else bool(chk.violated),
            "max_deviation": None if chk is None else chk.max_deviation,
            "detail": None if chk is None else chk.detail,
            "path_diverged": _fingerprint(src) != _fingerprint(fol),
            "source": side(src), "follow": side(fol)}


def _task(args):
    return run_case(*args)


def run_suite(mr_ids: Iterable[str] | None = None, modes=("natural",), seeds=config.SEEDS,
              workers: int | None = None) -> list[dict]:
    mr_ids = list(mr_ids or [m.id for m in CATALOG + REFINED])
    n_base = len(load_base_inputs())
    tasks = [(m, b, s, mode) for mode in modes for m in mr_ids for b in range(n_base) for s in seeds]
    workers = workers if workers is not None else max(1, min(8, (os.cpu_count() or 2) - 1))
    if workers > 1:
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init) as ex:
                return list(ex.map(_task, tasks, chunksize=8))
        except (OSError, PermissionError) as exc:
            print(f"[harness] process pool unavailable ({exc}); running serially")
    return [_task(t) for t in tasks]


def summarize(records: list[dict], mode: str) -> list[dict]:
    rows = []
    for mr in CATALOG + REFINED:
        all_rs = [r for r in records if r["mr"] == mr.id and r["mode"] == mode]
        rs = [r for r in all_rs if r.get("violated") is not None]
        if not rs:
            continue
        n, k = len(rs), sum(r["violated"] for r in rs)
        lo, hi = wilson_interval(k, n)
        bases = sorted({r["base_idx"] for r in rs})
        base_any = sum(any(r["violated"] for r in rs if r["base_idx"] == b) for b in bases)
        blo, bhi = wilson_interval(base_any, len(bases))
        seeds = sorted({r["seed"] for r in rs})
        per_seed = {str(s): sum(r["violated"] for r in rs if r["seed"] == s) / max(1, sum(r["seed"] == s for r in rs))
                    for s in seeds}
        flaky = sum(len({r["violated"] for r in rs if r["base_idx"] == b}) > 1 for b in bases)
        viol = [r for r in rs if r["violated"]]
        rows.append({
            "mr": mr.id, "name": mr.name, "family": mr.family, "refined": mr in REFINED,
            "n_executions": n, "n_not_applicable": sum(1 for r in all_rs if r.get("applicable") is False), "violations": k, "violation_rate": k / n, "ci95": [lo, hi],
            "n_base_inputs": len(bases), "bases_violated_any_seed": base_any,
            "base_violation_rate": base_any / len(bases), "base_ci95": [blo, bhi],
            "per_seed_rate": per_seed, "seed_sensitive_bases": flaky,
            "violations_with_path_divergence": sum(1 for r in viol if r.get("path_diverged")),
            "crashes": sum(1 for r in viol if r.get("error")),
        })
    return rows


def markdown_table(rows: list[dict], title: str) -> str:
    out = [f"### {title}", "",
           "| MR | Family | Relation | Violations / runs | Rate | 95% Wilson CI | Bases violated (any seed) | Seed-sensitive bases | Violations with control-path divergence |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        runs = f"{r['n_executions']}" + (f" (+{r['n_not_applicable']} outside subdomain)" if r["n_not_applicable"] else "")
        out.append(f"| {r['mr']} | {r['family']} | {r['name']} | {r['violations']} / {runs} | "
                   f"{r['violation_rate']:.1%} | [{r['ci95'][0]:.1%}, {r['ci95'][1]:.1%}] | "
                   f"{r['bases_violated_any_seed']} / {r['n_base_inputs']} | {r['seed_sensitive_bases']} | "
                   f"{r['violations_with_path_divergence']} |")
    return "\n".join(out)


def timed(fn, *a, **kw):
    t = time.time()
    out = fn(*a, **kw)
    return out, time.time() - t
