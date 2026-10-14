"""Confirmatory experiment for the MR2 diagnosis (pseudo-replication in the confidence bootstrap).

Hypothesis: MR2 violations happen because the Synthesizer's bootstrap treats duplicated ZIP-month
rows as independent evidence, so the follow-up's confidence rises and it skips refinements.

Intervention: before the monthly estimate, merge rows that share a (zipcode, month) key into one
stratum whose weight is the summed active count, so the bootstrap resamples ZIP-month strata rather
than rows. The real snapshot has exactly one row per ZIP-month, so the intervention is the identity
on every non-duplicated input; the script checks this by comparing all MR1 source runs.

    python scripts/confirm_mr2_pseudoreplication.py      -> results/mr2_confirmation.json
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.tools import StratifiedMedianTool  # noqa: E402
from mt import harness  # noqa: E402

_original = StratifiedMedianTool.monthly


def monthly_by_stratum(est_records, count_records, months, price, pool=1):
    key = ["zipcode", "month"]
    if est_records.duplicated(key).any():
        totals = est_records.groupby(key)["active_count"].transform("sum")
        est_records = est_records.assign(active_count=totals).loc[~est_records.duplicated(key)]
    return _original(est_records, count_records, months, price, pool)


def run(mr_ids):
    return harness.run_suite(mr_ids, modes=("natural",), workers=1)


def main() -> None:
    before = run(["MR1", "MR2"])
    StratifiedMedianTool.monthly = staticmethod(monthly_by_stratum)
    after = run(["MR1", "MR2"])
    StratifiedMedianTool.monthly = staticmethod(_original)

    def rows(recs, mr):
        return [r for r in recs if r["mr"] == mr]

    src_changed = sum(1 for a, b in zip(rows(before, "MR1"), rows(after, "MR1")) if a["source"] != b["source"])
    out = {}
    for label, recs in (("row_bootstrap (current system)", before), ("stratum_bootstrap (intervention)", after)):
        r2 = rows(recs, "MR2")
        v = sum(bool(r["violated"]) for r in r2)
        lo, hi = harness.wilson_interval(v, len(r2))
        out[label] = {"mr2_violations": v, "runs": len(r2), "rate": round(v / len(r2), 4),
                      "ci95": [round(lo, 4), round(hi, 4)],
                      "mr2_path_diverged": sum(r["path_diverged"] for r in r2),
                      "mr1_violations": sum(bool(r["violated"]) for r in rows(recs, "MR1"))}
    out["untransformed_source_runs_changed_by_intervention"] = src_changed
    path = os.path.join(ROOT, "results", "mr2_confirmation.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
