# Headline metamorphic-testing results

32 base inputs x 3 seeds [42, 101, 2026] per MR; 1728 executions in 42s.

### Natural mode (headline): follow-up run makes its own loop decisions

| MR | Family | Relation | Violations / runs | Rate | 95% Wilson CI | Bases violated (any seed) | Seed-sensitive bases | Violations with control-path divergence |
|---|---|---|---|---|---|---|---|---|
| MR1 | Invariance | Order / relabel invariance | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR2 | Invariance | Duplicate invariance | 31 / 96 | 32.3% | [23.8%, 42.2%] | 13 / 32 | 5 | 31 |
| MR3 | Invariance | Currency unit invariance (USD -> USD thousands) | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4 | Monotonic | Additive monotonicity in one month | 61 / 96 | 63.5% | [53.6%, 72.5%] | 25 / 32 | 13 | 4 |
| MR5 | Monotonic | Price-band widening monotonicity | 18 / 96 | 18.8% | [12.2%, 27.7%] | 6 / 32 | 0 | 18 |
| MR6 | Monotonic | Geographic restriction monotonicity | 18 / 96 | 18.8% | [12.2%, 27.7%] | 6 / 32 | 0 | 18 |
| MR7 | Directional | Window slide consistency | 10 / 96 | 10.4% | [5.8%, 18.1%] | 7 / 32 | 7 | 10 |
| MR8 | Directional | Multiplicative price scaling | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4R | Monotonic | Additive monotonicity, refined | 0 / 41 (+55 outside subdomain) | 0.0% | [0.0%, 8.6%] | 0 / 23 | 0 | 0 |

### Pinned ablation: follow-up replays the source run's control plan

| MR | Family | Relation | Violations / runs | Rate | 95% Wilson CI | Bases violated (any seed) | Seed-sensitive bases | Violations with control-path divergence |
|---|---|---|---|---|---|---|---|---|
| MR1 | Invariance | Order / relabel invariance | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR2 | Invariance | Duplicate invariance | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR3 | Invariance | Currency unit invariance (USD -> USD thousands) | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4 | Monotonic | Additive monotonicity in one month | 60 / 96 | 62.5% | [52.5%, 71.5%] | 25 / 32 | 13 | 0 |
| MR5 | Monotonic | Price-band widening monotonicity | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR6 | Monotonic | Geographic restriction monotonicity | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR7 | Directional | Window slide consistency | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR8 | Directional | Multiplicative price scaling | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4R | Monotonic | Additive monotonicity, refined | 0 / 41 (+55 outside subdomain) | 0.0% | [0.0%, 8.6%] | 0 / 23 | 0 | 0 |
