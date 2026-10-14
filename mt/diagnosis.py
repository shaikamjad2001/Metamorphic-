"""Root-cause evidence for violated MRs, computed from the case log (results/cases.jsonl).

For every violated MR it measures: the pinned-ablation rate (does the violation survive when the
follow-up is forced onto the source's control path?), which control decisions diverged, how close the
source sat to a decision threshold, and MR-specific evidence. The interpretation for the top three is
written from these numbers in REPORT.md.
"""
from __future__ import annotations

import collections
import json
import os
import sys
from statistics import mean, median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config  # noqa: E402
from backend.snapshot import month_add  # noqa: E402
from mt.relations import CATALOG  # noqa: E402

COMPONENTS = ("relaxation_level", "added_zips", "method", "refinements")


def _diverged_components(c: dict) -> list[str]:
    s, f = c.get("source") or {}, c.get("follow") or {}
    return [k for k in COMPONENTS if s.get(k) != f.get(k)]


def analyze(cases: list[dict]) -> dict:
    out = {}
    nat = [c for c in cases if c["mode"] == "natural"]
    pin = {(c["mr"], c["base_idx"], c["seed"]): c for c in cases if c["mode"] == "pinned"}
    for mr in CATALOG:
        rs = [c for c in nat if c["mr"] == mr.id]
        v = [c for c in rs if c.get("violated")]
        if not rs:
            continue
        survived = [c for c in v if pin.get((mr.id, c["base_idx"], c["seed"]), {}).get("violated")]
        comp = collections.Counter(k for c in v for k in _diverged_components(c))
        conf_gap = [abs(c["source"]["confidence"] - config.CONFIDENCE_TARGET) for c in v if c.get("source")]
        all_gap = [abs(c["source"]["confidence"] - config.CONFIDENCE_TARGET) for c in rs if c.get("source")]
        d = {
            "violations": len(v), "executions": len(rs),
            "violations_surviving_pinned_ablation": len(survived),
            "violations_with_control_divergence": sum(1 for c in v if c.get("path_diverged")),
            "diverged_components": dict(comp),
            "crashes": [c["error"] for c in v if c.get("error")][:3],
            "median_source_conf_distance_to_target_violated": round(median(conf_gap), 4) if conf_gap else None,
            "median_source_conf_distance_to_target_all": round(median(all_gap), 4) if all_gap else None,
            "examples": [{k: c.get(k) for k in ("base", "seed", "detail", "source", "follow")} for c in v[:3]],
        }
        if mr.id == "MR2":
            d["follow_confidence_minus_source_mean"] = round(mean(c["follow"]["confidence"] - c["source"]["confidence"]
                                                               for c in rs if c.get("follow")), 4)
            d["audit_verdict_flipped"] = sum(1 for c in v if c["source"]["audit_passed"] != c["follow"]["audit_passed"])
            d["fewer_refinements_in_follow_up"] = sum(1 for c in v if len(c["follow"]["refinements"]) < len(c["source"]["refinements"]))
            d["fewer_relaxations_in_follow_up"] = sum(1 for c in v if c["follow"]["relaxation_level"] < c["source"]["relaxation_level"])
        if mr.id == "MR4":
            cats = collections.Counter()
            for c in v:
                det, t = c["detail"], c["detail"]["target_month"]
                pooled = any(r.startswith("temporal_pool") for r in (c["source"]["refinements"] + c["follow"]["refinements"]))
                near = {month_add(t, k) for k in (-2, -1, 1, 2)}
                changed = set(det.get("other_months_changed") or [])
                crossings = (det.get("upper_band_crossings") or 0) + (det.get("lower_band_crossings") or 0)
                if det["target_decreased"] and crossings > 0:
                    cats["target month fell: records crossed a price-band bound (enter from below / exit above)"] += 1
                elif det["target_decreased"]:
                    cats["target month fell: no band crossing"] += 1
                if changed and pooled and changed <= near:
                    cats["neighbouring months moved: temporal pooling carries the +X into the pooling radius"] += 1
                elif changed and c.get("path_diverged"):
                    cats["non-adjacent months moved: refinement path diverged"] += 1
                elif changed:
                    cats["non-adjacent months moved: other"] += 1
            d["categories"] = dict(cats)
            d["categories_note"] = "a violation can fall in one 'target month' and one 'other months' category"
            rx = [c["detail"]["rise_over_x"] for c in rs if c["detail"].get("rise_over_x") is not None]
            hed = [c["detail"]["rise_over_x"] for c in rs if c["source"]["method"] == "hedonic" and c["detail"].get("rise_over_x") is not None]
            d["rise_over_x_all_median"] = round(median(rx), 4) if rx else None
            d["rise_over_x_hedonic_median"] = round(median(hed), 4) if hed else None
            d["rise_within_10pct_of_x_share"] = round(sum(0.9 <= r <= 1.1 for r in rx) / len(rx), 4) if rx else None
        if mr.id in ("MR5", "MR6"):
            d["source_relaxation_gt_follow"] = sum(1 for c in v if c["source"]["relaxation_level"] > c["follow"]["relaxation_level"])
            d["follow_relaxation_gt_source"] = sum(1 for c in v if c["follow"]["relaxation_level"] > c["source"]["relaxation_level"])
            d["follow_added_zips"] = sum(1 for c in v if c["follow"]["added_zips"] and not c["source"]["added_zips"])
            d["source_added_zips"] = sum(1 for c in v if c["source"]["added_zips"] and not c["follow"]["added_zips"])
            d["bases"] = sorted({c["base"] for c in v})
        if mr.id == "MR7":
            d["refinements_differ"] = sum(1 for c in v if c["source"]["refinements"] != c["follow"]["refinements"])
            d["method_differs"] = sum(1 for c in v if c["source"]["method"] != c["follow"]["method"])
            d["relaxation_differs"] = sum(1 for c in v if c["source"]["relaxation_level"] != c["follow"]["relaxation_level"])
        out[mr.id] = d
    ranked = sorted(out, key=lambda m: -out[m]["violations"])
    return {"by_mr": out, "top3": [m for m in ranked if out[m]["violations"]][:3]}


def to_markdown(diag: dict) -> str:
    lines = ["# Violation diagnosis evidence", "", f"Top three most-violated MRs: {', '.join(diag['top3'])}", ""]
    for mid, d in diag["by_mr"].items():
        if not d["violations"]:
            continue
        lines += [f"## {mid}", "",
                  f"- violations: {d['violations']} / {d['executions']}",
                  f"- survive pinned ablation: {d['violations_surviving_pinned_ablation']}",
                  f"- with control-path divergence: {d['violations_with_control_divergence']} "
                  f"(components: {d['diverged_components']})",
                  f"- median |source confidence - target|: violated {d['median_source_conf_distance_to_target_violated']} "
                  f"vs all {d['median_source_conf_distance_to_target_all']}"]
        for k, val in d.items():
            if k in ("violations", "executions", "violations_surviving_pinned_ablation", "examples",
                     "violations_with_control_divergence", "diverged_components", "crashes",
                     "median_source_conf_distance_to_target_violated", "median_source_conf_distance_to_target_all"):
                continue
            lines.append(f"- {k}: {val}")
        if d["crashes"]:
            lines.append(f"- crashes: {d['crashes']}")
        lines.append("")
    return "\n".join(lines)


def main(path: str = os.path.join(ROOT, "results")) -> None:
    with open(os.path.join(path, "cases.jsonl")) as f:
        cases = [json.loads(line) for line in f]
    diag = analyze(cases)
    with open(os.path.join(path, "diagnosis.json"), "w") as f:
        json.dump(diag, f, indent=2, default=str)
    with open(os.path.join(path, "diagnosis.md"), "w") as f:
        f.write(to_markdown(diag))
    print(to_markdown(diag))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results"))
