"""Writes runtime evidence that both loops fire: results/loop_trace.log (readable) and loop_trace.json.

Picks the first base input (in file order) whose run fires the feedback loop AND the refinement loop.
Usage:  python scripts/make_loop_trace.py [base_label] [seed]
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend import config  # noqa: E402
from backend.pipeline import run_pipeline  # noqa: E402
from backend.snapshot import load_snapshot  # noqa: E402
from mt.base_inputs import load_base_inputs  # noqa: E402


def render(r) -> str:
    lines = [f"criteria: {r.criteria.model_dump(exclude_none=True)}", f"seed: {r.seed}", ""]
    for e in r.events:
        tag = f"[{e.loop}#{e.iteration}]" if e.loop else ""
        detail = ", ".join(f"{k}={v}" for k, v in e.detail.items() if k not in ("thresholds",))
        lines.append(f"{e.step:>3} {e.elapsed_ms:>8.1f}ms  {e.agent:<16} {e.action:<22} {tag:<15} {detail}")
    lines += ["", f"control plan: {r.control.model_dump()}",
              f"confidence history: {r.diagnostics['confidence_history']}",
              f"audit history: {r.diagnostics['audit_history']}",
              f"supervisor halts: {r.diagnostics['supervisor_halts']}",
              "", r.narrative]
    return "\n".join(lines)


def main() -> int:
    snap = load_snapshot()
    bases = load_base_inputs()
    want = sys.argv[1] if len(sys.argv) > 1 else None
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else config.SEEDS[0]
    chosen = None
    for b in bases:
        if want and b.label != want:
            continue
        r = run_pipeline(b, snap, seed)
        if want or (r.diagnostics["feedback_cycles"] > 0 and r.diagnostics["refinement_cycles"] > 0):
            chosen = r
            break
    if chosen is None:
        print("no base input fired both loops")
        return 1
    out = os.path.join(ROOT, "results")
    os.makedirs(out, exist_ok=True)
    text = render(chosen)
    with open(os.path.join(out, "loop_trace.log"), "w") as f:
        f.write(text + "\n")
    with open(os.path.join(out, "loop_trace.json"), "w") as f:
        json.dump(chosen.model_dump(), f, indent=2, default=str)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
