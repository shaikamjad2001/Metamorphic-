# Design Note: Multi-Agent Dallas Housing Trends with Metamorphic Testing

TSE assignment, team: Vijay Arvaynthan S R (2023111007), Amjad Shaik (2025900012).

This is the final version of the design brief we submitted in the first ten days (`DESIGN_BRIEF.pdf`). Section 6 lists every place the built system differs from that brief, and why.

---

## 1. Agent architecture and control flow

Five functional agents and one supervisor. Agents are plain Python classes with typed inputs and outputs (pydantic). The assignment allows "no framework", so we use none. Each agent calls deterministic tools, and an LLM never produces a number.

```
                       ⟲ FEEDBACK LOOP (requirement a)
                 relax bands ±15/30/45%  |  add 2 nearest ZIPs
                ┌───────────────────────────────────┐
                ▼                                   │
User ─▶ 1 Orchestrator ─▶ 2 Data Scout ─scan─▶ 3 Quality Auditor
                                                    │ coverage ok
                                                    ▼  composition + sparsity signals choose the method (requirement c)
          TrendOutput ◀─conf ≥ 0.85── 5 Synthesizer ◀─draft── 4 Trend Specialist (hedonic | stratified median)
                                          │                         ▲
                                          └─────────────────────────┘
                                 ⟲ REFINEMENT LOOP (requirement b): confidence < 0.85
                                   robust_trim → temporal_pool_3 → temporal_pool_5

          Loop Supervisor guards both cycles: I1 cycle caps (≤3 each), I2 coverage monotone,
          I3 confidence must improve, I4 wall clock < 12 s
```

The UI's Agent Workflow tab draws the same graph and animates the arcs that fired in the run being viewed.

| Agent | Responsibility | Tools |
|---|---|---|
| Orchestrator | Validates `SearchCriteria`, resolves ZIP / city / tier to a ZIP set, builds the 12-month window plus up to two context months on each side | none |
| Data Scout | Slices the frozen snapshot for the ZIP set, window and (possibly relaxed) bands, and profiles the listing composition | `ListingFilterTool`, `MacroLookupTool`, `CompositionProfileTool` |
| Quality Auditor | Checks that each window month has ≥ 4 ZIPs and ≥ 40 active listings. On failure it returns a typed action: `relax_bands` or `expand_spatial` | none |
| Trend Specialist | Chooses hedonic or stratified median from upstream signals, then computes the series, change, CAGR, divergence and ZIP ranking. Applies refinement directives | `HedonicRegressionTool`, `StratifiedMedianTool`, `CagrCalculatorTool`, `MacroDivergenceTool` |
| Synthesizer | Seeded bootstrap confidence. Stops or requests the next refinement. Writes caveats and the narrative | none |
| Loop Supervisor | Approves or halts every cycle under invariants I1–I4 | none |

### Why the loops are necessary rather than decorative

- **Feedback loop.** In this data a tight price band on a small ZIP set often leaves months with only 1–3 ZIP-month records. A median over two records is not a trend. The auditor is the only agent that sees per-month adequacy, and only the scout can change the slice. So the work has to go back upstream. Across the 32 base inputs (×3 seeds) the loop fires in 51 of 96 runs (17 of 32 bases). It relaxes bands 69 times and expands the ZIP set 18 times. The supervisor stops it at the cap in 12 runs.
- **Refinement loop.** Confidence is measured, not asserted: it is the bootstrap width of each monthly median. When it is below 0.85 the Synthesizer cannot fix it itself, because only the Trend Specialist owns the estimator. It therefore sends a directive back. 73 of 96 runs end with pooled estimates, and 35 of 96 reach the 0.85 target. The rest deliver the best draft with caveats.
- **Genuine dependency.**
  - The auditor's action decides *which strategy* the scout runs next: widen the bands or add neighbouring ZIPs.
  - The scout's composition profile decides *which estimator* the Trend Specialist runs: hedonic if CV(sqft) > 0.30 or σ(bedrooms) > 0.50, otherwise stratified median. Extreme sparsity (≤ 2 ZIPs in some month) forces the stratified fallback.
  - The Synthesizer's directive decides *how* the next estimate is computed.

  Method split over the 96 source runs: 36 hedonic and 60 stratified.

### Output contract (what every MR talks about)

`TrendOutput` in `backend/schemas.py`:

- `monthly_series[m]` for each of the 12 window months:
  - `active_count`: Σ active listings over in-scope ZIP-month records
  - `median_price`: active-listing-weighted lower median of the ZIP-month median list prices, size-standardised if the method is hedonic
  - `median_price_per_sqft`
  - `price_q1`, `price_q3`
  - `n_zips`, `new_listings`, `median_dom`
  - `mom_pct_price`
- `trend_change_pct` (first to last month) and `annual_cagr_estimate` = ((P_end/P_start)^(12/(n−1)) − 1)·100
- `macro_divergence_score`: MAPD of the rebased series against Zillow ZHVI
- `zip_rankings` (per-ZIP change, ranked)
- `confidence`, `quality_audit_passed`, `method`, `currency_unit`

Each run also returns its `ControlPlan` (relaxation level, added ZIPs, method, refinements kept). This lets the harness tell an estimator change apart from a different control path.

## 2. Data source (real, frozen)

There is no synthetic or imputed value anywhere. `data/snapshot/MANIFEST.json` records `all_values_real: true` and the SHA-256 of every file. The harness refuses to run if a hash does not match.

| File | Source | Rows | Used for |
|---|---|---|---|
| `dfw_zip_month.csv` | Realtor.com Residential Listings Database, ZIP-level monthly history (`RDC_Inventory_Core_Metrics_Zip_History.csv`, 3.48 M upstream rows) | 6,205 ZIP-months, 137 ZIPs, 2022-12 to 2026-09 | What the agents scan |
| `dfw_listings_kaggle.csv` | Kaggle `ahmedshahriarsakib/usa-real-estate-dataset` (Realtor.com listings) | 25,356 listings in 136 ZIPs | Bedroom and size composition signal (method switch), listing explorer |
| `macro_monthly.csv` | Zillow ZHVI (Dallas metro); FRED MEDLISPRI19100, ACTLISCOU19100, MEDLISPRIPERSQUFEE19100, MORTGAGE30US; FHFA ATNHPIUS19124Q | 46 months | Cross-check and divergence score |
| `zillow_zip_zhvi.csv` | Zillow ZHVI by ZIP | | Context |
| `zip_geo.json` | US Census 2024 Gazetteer ZCTA centroids | 137 | Map, nearest-ZIP expansion, price tiers |

The Dallas metro is defined as ZIP3 750–753 within 40 miles of downtown Dallas (32.7767, −96.7970). Kaggle has real per-listing rows but only about six months of real dates, too few for a 12-month trend. The monthly trend therefore comes from Realtor.com's monthly ZIP records, which are real listing aggregates. The Kaggle listings provide per-listing composition.

Reproduction from scratch: `python scripts/fetch_raw_data.py && python scripts/build_snapshot.py`. The committed snapshot (2.6 MB) is what all results use.

## 3. Metamorphic relations (8 + 1 refined)

All eight are stated against the contract above. Tolerances are in `mt/relations.py`.

| MR | Family | Transformation | Relation | Subdomain | Tolerance | Fault targeted |
|---|---|---|---|---|---|---|
| MR1 | Invariance | Permute records, fresh record IDs | All monthly stats, Q1/Q3 and CAGR unchanged | All | rel ≤ 1e-5 | Order-dependent aggregation, unstable sort, order-dependent bootstrap |
| MR2 | Invariance | Append a copy of every record | Counts exactly double; medians unchanged | All | counts exact; rel ≤ 1e-5 | Unweighted averaging, count inflation, duplicate-key crashes |
| MR3 | Invariance | Prices ×0.001, unit USD → USD_K | Medians ×0.001; MoM, counts and ranking identical | Bounds in the same unit | ±0.05 (follow-up unit); MoM 1e-3 pp | Hard-coded dollar thresholds, unit-dependent rounding |
| MR4 | Monotonic | +$15,000 to every record in one window month | Target median does not fall; other months unchanged | Windows containing the month | Δ ≥ 0; rel ≤ 1e-5 | Temporal leakage across bins, sign errors |
| MR5 | Monotonic | Price band widened by ±$60,000 | Active count ≥ source in every month | Criteria with a price band | exact | Filter inversion, lossy joins |
| MR6 | Monotonic | ZIP set restricted to the first half | Active count ≤ source in every month | ≥ 2 ZIPs | exact | Spatial leakage, outer-join fallback |
| MR7 | Directional | Slide window +1 month | 11 overlapping months identical | Next month exists | rel ≤ 1e-5 | Off-by-one windows, window-dependent month processing |
| MR8 | Directional | Prices ×1.25 | Medians ×1.25; MoM, counts and ranking identical | All | ±$0.10; MoM 1e-3 pp | Non-linear estimator distortion, absolute thresholds |
| MR4R | Monotonic | As MR4 | Target does not fall; months *outside the pooling radius* unchanged | No in-scope target-month record crosses a band bound | as MR4 | Leakage beyond the declared pooling radius |

MR4R was added after diagnosing MR4. The assignment asks us to refine an MR that does not hold for the metric as specified, and MR4 does not; the final report explains why.

## 4. Statistical protocol

- **Base inputs:** 32 distinct base inputs (`mt/base_inputs.py`, generator seed 20261016):
  - 5 price tiers
  - 12 cities
  - 13 ZIP sets (the brief's 10 core ZIPs and their two halves, plus 10 random sets)
  - 2 whole-metro slices

  Every base has a price band, 9 also have a size band, and window ends range from 2023-12 to 2026-08.
- **Seeds:** [42, 101, 2026] for source and follow-up. The seed drives the bootstrap (`default_rng([seed, cycle])`) and the MR transformations.
- **Runs:** 32 × 3 = 96 runs per MR and mode. The violation rate gets a 95% Wilson interval. We also report the base-level any-seed rate, per-seed rates and seed-sensitive bases.
- **Modes:**
  - **Natural** (headline): the follow-up makes its own loop decisions.
  - **Pinned** (ablation): the follow-up replays the source's `ControlPlan`, so a violation that disappears under pinning was caused by the loops reacting, not by the estimator.
- **One command:** `python run_headline_results.py`. It runs 1,728 executions (9 MRs × 96 × 2 modes) in about 40 s on 8 processes.

## 5. Diagnosis plan

For each violated MR the harness records both control plans, whether the control path diverged, confidence distances to the target, and MR-specific evidence:

- MR4: band crossings and which months moved.
- MR5/MR6: relaxation and expansion differences.
- MR7: refinement differences.

`mt/diagnosis.py` turns this into `results/diagnosis.{json,md}`. The pinned ablation is the main instrument for separating the four cause classes: genuine fault, data artifact, ill-conceived MR, harness bug.

## 6. Changes from the submitted brief

| Brief | Built | Why |
|---|---|---|
| 4,786-row listing file, 10 core ZIPs, window 2023 | Realtor.com ZIP-month records, 137 ZIPs, 2022-12 to 2026-09; Kaggle listings for composition | The assignment and the team asked for real data. No public per-listing source has 12+ months of real dates for Dallas. |
| Auditor: N ≥ 10 active listings per month | ≥ 4 distinct ZIPs **and** ≥ 40 active listings per month | The scanned unit is a ZIP-month aggregate, so "submarkets per month" is the meaningful adequacy measure |
| Refinement action unspecified | `robust_trim` (3.5 MAD on $/sqft, only in months with ≥ 8 distinct ZIPs) → `temporal_pool_3` → `temporal_pool_5`; best draft kept | Needed a concrete refinement. The ≥ 8-ZIP guard came from the MR4 diagnosis. |
| 6 tools | 7 (+ `CompositionProfileTool`) | Composition is the method-switch signal |
| Base slices varied by bedroom thresholds | Varied by tier, city, ZIP set, price and size bands | ZIP-month data has no bedroom breakdown |
| 768 executions | 1,728 (adds the pinned ablation and MR4R) | Needed for diagnosis |
