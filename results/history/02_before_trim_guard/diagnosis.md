# Violation diagnosis evidence

Top three most-violated MRs: MR4, MR2, MR5

## MR2

- violations: 24 / 96
- survive pinned ablation: 0
- with control-path divergence: 24 (components: {'refinements': 24})
- median |source confidence - target|: violated 0.0534 vs all 0.0812
- follow_confidence_minus_source_mean: 0.0545
- audit_verdict_flipped: 0
- fewer_refinements_in_follow_up: 18
- fewer_relaxations_in_follow_up: 0

## MR4

- violations: 40 / 96
- survive pinned ablation: 40
- with control-path divergence: 4 (components: {'refinements': 4})
- median |source confidence - target|: violated 0.0631 vs all 0.0812
- categories: {'target month fell: records pushed over the upper price bound': 4, 'neighbouring months moved: temporal pooling carries the +X into the pooling radius': 32, 'non-adjacent months moved: refinement path diverged': 4, 'target month fell: other cause': 3}
- rise_over_x_all_median: 0.7811
- rise_over_x_hedonic_median: 0.4982
- rise_within_10pct_of_x_share: 0.4583

## MR5

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 18, 'refinements': 3})
- median |source confidence - target|: violated 0.1401 vs all 0.0812
- source_relaxation_gt_follow: 18
- follow_relaxation_gt_source: 0
- follow_added_zips: 0
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B08-city-Irving', 'B14-city-Carrollton', 'B23-zips-7zips', 'B29-zips-7zips', 'B30-zips-15zips']

## MR6

- violations: 18 / 96
- survive pinned ablation: 0
- with control-path divergence: 18 (components: {'relaxation_level': 9, 'added_zips': 12, 'refinements': 7, 'method': 3})
- median |source confidence - target|: violated 0.2019 vs all 0.0812
- source_relaxation_gt_follow: 0
- follow_relaxation_gt_source: 9
- follow_added_zips: 6
- source_added_zips: 0
- bases: ['B07-city-Plano', 'B12-city-Richardson', 'B14-city-Carrollton', 'B20-zips-5zips', 'B22-zips-12zips', 'B26-zips-13zips']

## MR7

- violations: 17 / 96
- survive pinned ablation: 0
- with control-path divergence: 17 (components: {'refinements': 17})
- median |source confidence - target|: violated 0.0418 vs all 0.0812
- refinements_differ: 17
- method_differs: 0
- relaxation_differs: 0
