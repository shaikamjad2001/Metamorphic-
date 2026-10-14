#!/usr/bin/env python3
"""One-command reproduction of the headline metamorphic-testing results table.

    python run_headline_results.py                 # natural (headline) + pinned ablation, all 8 MRs
    python run_headline_results.py --out results/x # write somewhere else
    python run_headline_results.py --workers 1     # serial (identical numbers, slower)

Reads only data/snapshot/ (frozen). Seeds, base inputs and every threshold are recorded in the output.
Writes  <out>/headline_results.json, <out>/headline_table.md, <out>/cases.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from backend import config  # noqa: E402
from mt.base_inputs import GENERATOR_SEED, PATH as BASE_PATH, load_base_inputs  # noqa: E402
from mt.harness import markdown_table, run_suite, summarize  # noqa: E402
from mt.relations import CATALOG, REFINED  # noqa: E402


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def verify_snapshot() -> dict:
    with open(os.path.join(config.SNAPSHOT_DIR, "MANIFEST.json")) as f:
        expected = json.load(f)["snapshot_sha256"]
    actual = {name: _sha(os.path.join(config.SNAPSHOT_DIR, name)) for name in expected}
    bad = [n for n in expected if expected[n] != actual[n]]
    if bad:
        sys.exit(f"Frozen snapshot does not match MANIFEST.json: {bad}")
    return actual


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--modes", default="natural,pinned")
    ap.add_argument("--mrs", default=None, help="comma-separated subset, e.g. MR1,MR2")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    hashes = verify_snapshot()
    bases = load_base_inputs()
    modes = tuple(args.modes.split(","))
    mr_ids = args.mrs.split(",") if args.mrs else None
    print(f"Snapshot verified ({len(hashes)} files). {len(bases)} base inputs x seeds {list(config.SEEDS)} "
          f"x {len(mr_ids or CATALOG + REFINED)} MRs x modes {list(modes)}")
    t0 = time.time()
    records = run_suite(mr_ids, modes=modes, workers=args.workers)
    elapsed = time.time() - t0

    tables = {mode: summarize(records, mode) for mode in modes}
    result = {
        "generated_by": "run_headline_results.py",
        "python": platform.python_version(),
        "elapsed_seconds": round(elapsed, 1),
        "snapshot_sha256": hashes,
        "seeds": list(config.SEEDS),
        "base_inputs": {"n": len(bases), "generator_seed": GENERATOR_SEED, "file": os.path.relpath(BASE_PATH, ROOT),
                        "labels": [b.label for b in bases]},
        "protocol": "violation rate over (base input x seed) executions; Wilson score 95% CI (z = 1.96). "
                    "Base-level rate counts a base as violated if any seed violates.",
        "config": {k: getattr(config, k) for k in dir(config) if k.isupper() and k not in ("ROOT", "SNAPSHOT_DIR", "RESULTS_DIR")},
        "catalog": [m.catalog() for m in CATALOG + REFINED],
        "results": tables,
    }
    with open(os.path.join(args.out, "headline_results.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)
    with open(os.path.join(args.out, "cases.jsonl"), "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    md = [f"# Headline metamorphic-testing results", "",
          f"{len(bases)} base inputs x {len(config.SEEDS)} seeds {list(config.SEEDS)} per MR; "
          f"{len(records)} executions in {elapsed:.0f}s.", ""]
    titles = {"natural": "Natural mode (headline): follow-up run makes its own loop decisions",
              "pinned": "Pinned ablation: follow-up replays the source run's control plan"}
    for mode in modes:
        md += [markdown_table(tables[mode], titles.get(mode, mode)), ""]
    with open(os.path.join(args.out, "headline_table.md"), "w") as f:
        f.write("\n".join(md))
    print("\n".join(md))
    if "natural" in modes and "pinned" in modes:
        from mt.diagnosis import analyze, to_markdown
        diag = analyze(records)
        with open(os.path.join(args.out, "diagnosis.json"), "w") as f:
            json.dump(diag, f, indent=2, default=str)
        with open(os.path.join(args.out, "diagnosis.md"), "w") as f:
            f.write(to_markdown(diag))
    print(f"\nWrote {os.path.relpath(args.out, ROOT)}/headline_results.json, headline_table.md, cases.jsonl, diagnosis.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
