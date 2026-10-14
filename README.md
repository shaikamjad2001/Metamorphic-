# DFW Housing Trends: Multi-Agent Analysis with Metamorphic Testing

A multi-agent application for TSE (Topics in Software Engineering). It reports how Dallas-area list prices moved over a 12-month window, using a frozen snapshot of **real** public data (Realtor.com, Kaggle/Realtor.com listings, Zillow, FRED, FHFA, US Census). A metamorphic-testing harness evaluates eight relations statistically.

Team: Vijay Arvaynthan S R, Amjad Shaik.

| Document | Contents |
|---|---|
| [`REPORT.md`](REPORT.md) | Final report: system, data, MR catalog, results with 95% CIs, root-cause analysis, threats, reflection |
| [`DESIGN_NOTE.md`](DESIGN_NOTE.md) | Architecture graph with cycles, data sources, output contract, MR sketches, changes from the brief |
| [`NOTEBOOK.md`](NOTEBOOK.md) | Seeds, commands, and the chronological log of runs and fixes |
| [`AI_USE.md`](AI_USE.md) | Disclosure of AI use, including where the tool was wrong |

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Headline results table (one command; verifies snapshot hashes; ~40 s on 8 cores)
.venv/bin/python run_headline_results.py
cat results/headline_table.md

# Web UI (builds the frontend on first start; needs Node 20+)
.venv/bin/python start.py              # http://127.0.0.1:8000  (use --port 8010 if 8000 is taken)
```

Other commands:

```bash
.venv/bin/python scripts/make_loop_trace.py                 # execution trace with both loops firing
.venv/bin/python scripts/confirm_mr2_pseudoreplication.py   # causal check of the MR2 diagnosis
.venv/bin/python -m pytest -q                               # 14 tests
.venv/bin/python scripts/fetch_raw_data.py && .venv/bin/python scripts/build_snapshot.py   # rebuild snapshot from sources
cd frontend && npm install && npm run dev                   # UI dev server (proxies /api to :8000)
```

## Headline results (natural mode, 32 base inputs × seeds 42/101/2026)

| MR | Relation | Violations | Rate | 95% Wilson CI | Pinned ablation |
|---|---|---|---|---|---|
| MR1 | Order / relabel invariance | 0/96 | 0.0% | [0.0, 3.8] | 0/96 |
| MR2 | Duplicate invariance | 31/96 | 32.3% | [23.8, 42.2] | 0/96 |
| MR3 | Currency unit invariance | 0/96 | 0.0% | [0.0, 3.8] | 0/96 |
| MR4 | +$15k in one month | 61/96 | 63.5% | [53.6, 72.5] | 60/96 |
| MR5 | Price-band widening | 18/96 | 18.8% | [12.2, 27.7] | 0/96 |
| MR6 | ZIP subset | 18/96 | 18.8% | [12.2, 27.7] | 0/96 |
| MR7 | Window slide | 10/96 | 10.4% | [5.8, 18.1] | 0/96 |
| MR8 | ×1.25 price scaling | 0/96 | 0.0% | [0.0, 3.8] | 0/96 |
| MR4R | MR4, refined | 0/41 | 0.0% | [0.0, 8.6] | 0/41 |

The diagnosis of MR4, MR2 and MR5 (plus MR6 and MR7) is in `REPORT.md` §6.

## Ask the Agents (chat)

The default tab of the UI is a chatbot over the snapshot. Each question is planned into one of eight intents (trend, compare, rank, listings, macro, testing, system, help); market questions run the full agent pipeline once per slice, and `POST /api/chat` streams every agent event as NDJSON. The right-hand panel replays those events on the agent graph (the active agent pulses, and the feedback and refinement loop counters light up when they fire) next to a step-by-step log.

Examples: "How did prices change in Plano?", "Compare Frisco vs McKinney under $700k", "Which ZIPs fell the most in Dallas?", "Luxury homes 2024 vs 2025", "3 bedroom homes in 75204", "What happened to mortgage rates?", "Which MR was violated most and why?". Follow-ups such as "what about ZIPs in Dallas?" reuse the previous intent. "Test MR5", "Show me an MR2 violation" or "Run MR4 on base 3 seed 101 pinned" re-run a real harness case live (source run, transformation, follow-up run, relation check) and stream both runs on the agent graph.

The Metamorphic Lab tab does the same interactively: click a relation in the results table, then click any cell in the 32 base inputs × 3 seeds grid of recorded verdicts (or "Run a violating case") to re-run that case and compare the two runs' agent paths side by side. Every recorded violation reproduces exactly when re-run (fixed seeds, frozen snapshot). `http://127.0.0.1:8010/?q=<question>#chat` asks a question on load.

Without an LLM key, planning and answer wording are rule-based. With one configured in `.env` (see `.env.example`), the LLM plans the question and phrases the answer from the computed facts only; the numbers always come from the agents.

## Layout

```
backend/            agents (orchestrator, data_scout, quality_auditor, trend_specialist, synthesizer, loop_supervisor),
                    tools, pipeline (control graph), schemas (output contract), FastAPI app, optional LLM parser
mt/                 base inputs, MR catalog, harness (natural + pinned modes), diagnosis
data/snapshot/      frozen real-data snapshot + MANIFEST.json (sources, filters, SHA-256)
results/            headline table/json, per-case records, diagnosis, loop trace, fix history, screenshots
scripts/            fetch raw data, build snapshot, make loop trace, MR2 confirmation
frontend/           React + TypeScript + Tailwind + Recharts + Leaflet UI
tests/              system and regression tests
```

## Notes

- **No synthetic data.** `data/snapshot/MANIFEST.json` records `all_values_real: true` and `synthetic_or_imputed_values: "none"`.
- **LLM is optional.** It is used only to plan chat questions, parse free-text criteria, and phrase chat answers; see `.env.example`. The analysis and the harness are deterministic and LLM-free.
- **Process pool.** If your environment forbids process pools, the harness falls back to serial execution automatically, or you can pass `--workers 1`.
