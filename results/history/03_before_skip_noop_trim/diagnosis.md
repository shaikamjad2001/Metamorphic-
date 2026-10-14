# Violation diagnosis evidence

Top three most-violated MRs: MR2, MR4, MR7

## MR2

- violations: 35 / 96
- survive pinned ablation: 0
- with control-path divergence: 35 (components: {'refinements': 35})
- median |source confidence - target|: violated 0.1329 vs all 0.1038
- follow_confidence_minus_source_mean: 0.0607
- audit_verdict_flipped: 0
- fewer_refinements_in_follow_up: 22
- fewer_relaxations_in_follow_up: 0

## MR4

- violations: 34 / 96
- survive pinned ablation: 32
- with control-path divergence: 3 (components: {'refinements': 3})
- median |source confidence - target|: violated 0.0631 vs all 0.1038
- categories: {'target month fell: records pushed over the upper price bound': 3, 'neighbouring months moved: temporal pooling carries the +X into the pooling radius': 28, 'target month fell: other cause': 3, 'non-adjacent months moved: refinement path diverged': 3}
- rise_over_x_all_median: 0.8803
- rise_over_x_hedonic_median: 0.5676
- rise_within_10pct_of_x_share: 0.4896

## MR5

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 18, 'refinements': 4})
- median |source confidence - target|: violated 0.2729 vs all 0.1038
- source_relaxation_gt_follow: 18
- follow_relaxation_gt_source: 0
- follow_added_zips: 0
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B08-city-Irving', 'B14-city-Carrollton', 'B23-zips-7zips', 'B29-zips-7zips', 'B30-zips-15zips']

## MR6

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 9, 'added_zips': 12, 'refinements': 7, 'method': 3})
- median |source confidence - target|: violated 0.2245 vs all 0.1038
- source_relaxation_gt_follow: 0
- follow_relaxation_gt_source: 9
- follow_added_zips: 6
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B12-city-Richardson', 'B14-city-Carrollton', 'B20-zips-5zips', 'B22-zips-12zips', 'B26-zips-13zips']

## MR7

- violations: 31 / 96
- survive pinned ablation: 0
- with control-path divergence: 31 (components: {'refinements': 31})
- median |source confidence - target|: violated 0.1791 vs all 0.1038
- refinements_differ: 31
- method_differs: 0
- relaxation_differs: 0
