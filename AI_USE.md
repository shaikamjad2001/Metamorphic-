# AI_USE

The assignment encourages using LLMs and agents. This file discloses every substantive use, including the places where the tool was wrong and how we caught it.

## Tools

- **Cursor's AI coding agent** (chat-driven, with terminal access in the repository). We used it to:
  - write the data download and snapshot scripts, backend agents, tools, harness, tests and the React UI;
  - run the harness and read results;
  - draft the design note, this notebook and the report.
- **No LLM inside the system's numbers.** The agents are deterministic Python. An optional LLM (temperature 0, Ollama, LM Studio or Gemini, configured in `.env`) only parses free-text questions into search criteria in the UI. A rule-based parser does the same with no LLM. The metamorphic harness never calls an LLM.

## What the AI produced vs what we decided

| Area | AI contribution | Our decision / verification |
|---|---|---|
| Architecture | Implemented the agent roster, tools and loop supervisor from our design brief | The brief (agents, thresholds 0.30/0.50, relaxation 15/30/45%, ≤ 3 cycles, < 12 s, MR1–MR8) is ours. We checked that the trace shows each loop firing |
| Data | Proposed replacing per-listing Kaggle dates with Realtor.com ZIP-month history; wrote fetch and build scripts | We required real data only. We checked the manifest, hashes and row counts, and compared the metro series with FRED |
| MR catalog | Encoded MR1–MR8 from the brief; proposed MR4R after diagnosis | We reviewed tolerances and subdomains, and decided to report MR4 as stated plus MR4R |
| Diagnosis | Built the evidence extraction (pinned ablation, path fingerprints, MR-specific details) and the MR2 intervention script | We reviewed each category against raw cases (below) |
| Report | Drafted the text from the generated results | We checked each number against `results/` |

## Where the AI was wrong, and how it was caught

1. **Ranking crash on duplicates.** The first `zip_rankings` assumed one row per ZIP-month. *Caught by:* MR2 crashing in 96/96 runs on the first full harness run. Fixed, and a regression test added.
2. **Unstable outlier trim.** The AI's `robust_trim` applied a 3.5-MAD rule even to months with 4 ZIPs, so +$15k could make it drop the heaviest record and move the median by $166k. *Caught by:* MR4R violations that persisted under pinning. Fixed with a ≥ 8 distinct-ZIP guard, and a regression test added.
3. **A fix with a side effect.** After the trim guard, the Synthesizer still requested a trim that could no longer change anything. I3 then halted refinement, and MR7 violations nearly doubled (17 → 31). *Caught by:* comparing archived headline tables across stages (`results/history/`). Fixed by skipping inapplicable directives.
4. **Wrong reference value in a test.** The AI hand-computed the Wilson lower bound for 18/96 as 0.1219; the correct value is 0.1220. *Caught by:* the test failing against the implementation. We checked the value independently and corrected the test, not the code.
5. **Keyword collision in the trace logger.** Detail keys named `action` collided with `Trace.log(agent, action, ...)` and raised at run time. *Caught by:* the first pipeline run. Keys renamed to `next_action` and `feedback_action`.
6. **Diagnosis mislabelling.** The MR4 categoriser counted only *upper*-bound crossings and called the remaining target-month decreases "other cause". *Caught by:* reading the six raw cases while writing the report. All six had lower-bound crossings. Label fixed; the report states the categories overlap.
7. **Non-neutral intervention.** The first MR2 confirmation collapsed identical (value, weight) pairs and changed 17/96 untransformed runs. A tool that only reported "MR2 → 0" would have overstated the result. *Caught by:* the script's own neutrality check. Replaced by the (ZIP, month) key version, with 0 untransformed runs changed.
8. **Initial expectation about MR2.** The AI's first reading was that MR2 would fail on counts or medians. The data showed medians and counts are fine and the failure is in the controller. *Caught by:* the pinned ablation (0/96 when pinned).
9. **UI issues.**
   - The map tile provider (CARTO) now requires an API key and rendered "API KEY REQUIRED" tiles. Switched to Esri's light-gray canvas.
   - SVG labels in the workflow graph overlapped.
   - Tailwind v4 rejected `@apply` of a custom class.

   *Caught by:* headless-browser screenshots and the build.
10. **Natural-language parser.** A bare year ("in 2024") was not recognised until the regex was fixed. *Caught by:* manual testing in the UI.

## Things the AI surfaced that we kept as documented limitations

- Look-ahead from centred pooling with ±2 context months. MR7's pinned pass depends on it.
- Confidence tracks precision, not accuracy. Pooling can move the point estimate a lot.
- `active_count` reports the relaxed band rather than the user's band (MR5).

## Secrets

An earlier prototype's `.env` contained API keys. They were not copied, printed or committed. `.env` is git-ignored, and `.env.example` documents the optional variables with empty values.
