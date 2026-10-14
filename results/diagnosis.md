# Violation diagnosis evidence

Top three most-violated MRs: MR4, MR2, MR5

## MR2

- violations: 31 / 96
- survive pinned ablation: 0
- with control-path divergence: 31 (components: {'refinements': 31})
- median |source confidence - target|: violated 0.0257 vs all 0.0693
- follow_confidence_minus_source_mean: 0.0506
- audit_verdict_flipped: 0
- fewer_refinements_in_follow_up: 30
- fewer_relaxations_in_follow_up: 0

## MR4

- violations: 61 / 96
- survive pinned ablation: 60
- with control-path divergence: 4 (components: {'refinements': 4})
- median |source confidence - target|: violated 0.0745 vs all 0.0693
- categories: {'target month fell: records crossed a price-band bound (enter from below / exit above)': 6, 'neighbouring months moved: temporal pooling carries the +X into the pooling radius': 56, 'non-adjacent months moved: refinement path diverged': 4}
- categories_note: a violation can fall in one 'target month' and one 'other months' category
- rise_over_x_all_median: 0.2902
- rise_over_x_hedonic_median: 0.4634
- rise_within_10pct_of_x_share: 0.1458

## MR5

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 18, 'refinements': 3})
- median |source confidence - target|: violated 0.1307 vs all 0.0693
- source_relaxation_gt_follow: 18
- follow_relaxation_gt_source: 0
- follow_added_zips: 0
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B08-city-Irving', 'B14-city-Carrollton', 'B23-zips-7zips', 'B29-zips-7zips', 'B30-zips-15zips']

## MR6

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 9, 'added_zips': 12, 'method': 3, 'refinements': 3})
- median |source confidence - target|: violated 0.0993 vs all 0.0693
- source_relaxation_gt_follow: 0
- follow_relaxation_gt_source: 9
- follow_added_zips: 6
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B12-city-Richardson', 'B14-city-Carrollton', 'B20-zips-5zips', 'B22-zips-12zips', 'B26-zips-13zips']

## MR7

- violations: 10 / 96
- survive pinned ablation: 0
- with control-path divergence: 10 (components: {'refinements': 10})
- median |source confidence - target|: violated 0.0345 vs all 0.0693
- refinements_differ: 10
- method_differs: 0
- relaxation_differs: 0
