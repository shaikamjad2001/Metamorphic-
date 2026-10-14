# NOTEBOOK

Working log: decisions, runs, seeds and fixes, in the order they happened. Numbers refer to the files in `results/`.

## Fixed parameters

| What | Value | Where |
|---|---|---|
| Seeds (source and follow-up) | 42, 101, 2026 | `backend/config.py: SEEDS` |
| Base-input generator seed | 20261016 | `mt/base_inputs.py` |
| Bootstrap RNG | `numpy.random.default_rng([seed, refinement_cycle])`, 200 resamples | `backend/agents/synthesizer.py` |
| MR transformation RNG | derived from the run seed (MR1 permutation, MR4 target month) | `mt/relations.py` |
| Snapshot | `dfw-real-2026-10`, SHA-256 per file in `data/snapshot/MANIFEST.json` | verified by `run_headline_results.py` |
| Python / libraries | Python 3.14, pandas 3.0.6, numpy 2.5.4, pydantic 2.14.1 | `requirements.txt` |

## How to reproduce each artifact

| Artifact | Command | Time |
|---|---|---|
| Headline table, cases, diagnosis | `python run_headline_results.py` (`--workers 1` for serial) | ~40 s on 8 processes, a few minutes serial |
| Loop trace | `python scripts/make_loop_trace.py` | 1 s |
| MR2 confirmation | `python scripts/confirm_mr2_pseudoreplication.py` | ~40 s |
| Tests | `python -m pytest -q` | 3 s |
| Snapshot from raw sources | `python scripts/fetch_raw_data.py && python scripts/build_snapshot.py` | network-bound, ~1.1 GB download |
| UI | `python start.py` then open http://127.0.0.1:8000 | |

Port 8000 may already be in use by another app; then run `python start.py --port 8010`.

## Log

### Data

- **Kaggle has no 12-month date range.** The suggested Kaggle file has real Dallas listings, but only about six months of real dates. A 12-month trend cannot be built from it without inventing dates. **Decision:** scan Realtor.com's ZIP-level monthly inventory history, which is real and has monthly granularity back to 2016. Keep Kaggle for per-listing composition.
- **Metro filter.** ZIP3 750–753, then within 40 miles of downtown Dallas using Census ZCTA centroids. Result: 137 ZIPs, 46 months (2022-12 to 2026-09), 6,205 ZIP-months. 97 ZIP-months are missing upstream and are left missing, not imputed.
- **Sanity check.** Macro series (ZHVI, FRED median list price and inventory, mortgage rate, FHFA) were downloaded for the cross-check chart. Our whole-metro run picks the hedonic method, standardised to 1,800 sqft, so its level is 7–11% below the FRED Realtor.com MSA median. Month-to-month correlation with FRED is 0.72, 0.88 and 0.89 for windows ending 2024-09, 2025-09 and 2026-09. The 12-month change agrees in sign for the windows ending 2025-09 and 2026-09 (ours −0.06% and −1.04%, FRED −1.73% and −0.59%). It disagrees for 2024-09 (ours +0.98%, FRED −2.23%).
- **Quality flags kept.** Realtor.com `quality_flag = 1` marks 2,205 ZIP-months. Kept, because they are the published values (see the report's threats section).

### System calibration

- **Threshold choice.** We ran all 32 bases × 3 seeds and looked at how often each loop fires. Final thresholds:
  - ≥ 4 ZIPs and ≥ 40 active listings per month;
  - confidence target 0.85;
  - stability scale 0.35.

  With these, the feedback loop fires on 17/32 bases (51/96 runs), 73/96 runs pool, and 35/96 converge. The goal was for both loops to fire on a substantial share of inputs, without either never or always firing.
- **Lower weighted median.** Chosen so medians are observed values, which keeps invariance MRs exact.
- **Bootstrap order.** Resampling uses canonical content order (sort by value, then weight), so MR1 also covers confidence.

### Metamorphic runs (natural mode unless stated)

1. **Stage 1, first full run** (`results/history/01_before_ranking_fix`). MR2 failed 96/96, all crashes: `float()` on a Series in `zip_rankings` when a ZIP-month appears twice. **Fix:** weighted median per ZIP-month. A regression test was added.
2. **Stage 2** (`02_before_trim_guard`). MR2 24, MR4 40, MR7 17, MR4R 2. Investigating MR4R on B28 (seed 2026, pinned):
   - in a 4-ZIP month, +$15k pushed 75219's $/sqft past 3.5 MAD;
   - `robust_trim` dropped the record with 282 active listings;
   - the median fell by $166k.

   **Fix:** only trim months with ≥ 8 distinct ZIPs. We count distinct ZIPs, not rows, so MR2 cannot change the decision. A regression test was added.
3. **Stage 3** (`03_before_skip_noop_trim`). MR2 35, MR4 34, MR7 31. The trim guard made `robust_trim` a no-op on small slices, but the Synthesizer still spent a cycle on it, and I3 ("no confidence gain") then halted refinement. **Fix:** the Synthesizer skips `robust_trim` when no month qualifies.
4. **Stage 4, current.** MR1 0, MR2 31, MR3 0, MR4 61, MR5 18, MR6 18, MR7 10, MR8 0, MR4R 0/41. Pinned: everything 0 except MR4, at 60.
   - The MR4 rise follows from stage 3's fix: pooling went from 33/96 to 73/96 source runs.
   - All MR4 violations except one involve pooling, and every changed month is inside the ±2-month radius. This led to MR4R.
5. **MR2 diagnosis check** (`scripts/confirm_mr2_pseudoreplication.py`).
   - **First attempt:** collapse identical (value, weight) pairs before bootstrapping. MR2 went to 0, but 17/96 *untransformed* source runs also changed, because pooled samples contain coincidentally identical pairs. **Rejected** as a non-neutral intervention.
   - **Second attempt:** merge rows sharing a (ZIP, month) key. MR2 went from 31/96 to 0/96, and 0/96 untransformed runs changed. Pseudo-replication is confirmed as the cause.
6. **Diagnosis category fix.** `mt/diagnosis.py` labelled MR4 target-month decreases without an *upper*-bound crossing as "other cause". On inspection, all 6 decreases had a lower-bound crossing, where records enter the band from below, so the label was changed to "crossed a price-band bound". The categories overlap: a case can be both "target fell" and "neighbours moved". The output now says so.

### Things noticed and documented rather than changed

- **Look-ahead.** Centred pooling plus ±2 context months means the last window months can read up to two months past the window end. MR7 holds under pinning *because* of this padding. Clipping would break MR7 by construction. This is documented in the report as a validity threat.
- **Precision vs bias.** In the trace example, `temporal_pool_5` raised confidence from 0.68 to 0.71 but moved the 12-month change from −0.04% to +11.8%. Confidence measures estimator stability, not correctness.
- **MR5 contract ambiguity.** `active_count` reports the relaxed band. A contract change that reports counts for the user's original band was proposed, not implemented.
