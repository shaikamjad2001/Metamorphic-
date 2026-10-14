# Headline metamorphic-testing results

32 base inputs x 3 seeds [42, 101, 2026] per MR; 1536 executions in 45s.

### Natural mode (headline): follow-up run makes its own loop decisions

| MR | Family | Relation | Violations / runs | Rate | 95% Wilson CI | Bases violated (any seed) | Seed-sensitive bases | Violations with control-path divergence |
|---|---|---|---|---|---|---|---|---|
| MR1 | Invariance | Order / relabel invariance | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR2 | Invariance | Duplicate invariance | 96 / 96 | 100.0% | [96.2%, 100.0%] | 32 / 32 | 0 | 0 |
| MR3 | Invariance | Currency unit invariance (USD -> USD thousands) | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4 | Monotonic | Additive monotonicity in one month | 40 / 96 | 41.7% | [32.3%, 51.7%] | 20 / 32 | 14 | 4 |
| MR5 | Monotonic | Price-band widening monotonicity | 18 / 96 | 18.8% | [12.2%, 27.7%] | 6 / 32 | 0 | 18 |
| MR6 | Monotonic | Geographic restriction monotonicity | 18 / 96 | 18.8% | [12.2%, 27.7%] | 6 / 32 | 0 | 18 |
| MR7 | Directional | Window slide consistency | 17 / 96 | 17.7% | [11.4%, 26.5%] | 14 / 32 | 14 | 17 |
| MR8 | Directional | Multiplicative price scaling | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |

### Pinned ablation: follow-up replays the source run's control plan

| MR | Family | Relation | Violations / runs | Rate | 95% Wilson CI | Bases violated (any seed) | Seed-sensitive bases | Violations with control-path divergence |
|---|---|---|---|---|---|---|---|---|
| MR1 | Invariance | Order / relabel invariance | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR2 | Invariance | Duplicate invariance | 96 / 96 | 100.0% | [96.2%, 100.0%] | 32 / 32 | 0 | 0 |
| MR3 | Invariance | Currency unit invariance (USD -> USD thousands) | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR4 | Monotonic | Additive monotonicity in one month | 40 / 96 | 41.7% | [32.3%, 51.7%] | 20 / 32 | 14 | 0 |
| MR5 | Monotonic | Price-band widening monotonicity | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR6 | Monotonic | Geographic restriction monotonicity | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR7 | Directional | Window slide consistency | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
| MR8 | Directional | Multiplicative price scaling | 0 / 96 | 0.0% | [0.0%, 3.8%] | 0 / 32 | 0 | 0 |
