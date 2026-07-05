---
name: question-intake
description: Use first in the forecast workflow to turn a vague user question into a strict, resolvable QuestionSpec before any forecasting begins.
---

# question-intake

Turn a vague user question into a strict, resolvable **QuestionSpec** (schema
§7.1). This is where most amateur forecasting fails, so be strict: the target is
a question two strangers, reading only the resolution criteria on resolution
day, would resolve identically.

## Playbook

1. **Classify the type** — binary / multiple-choice / numeric / date. v1 scores
   binaries only; reduce everything else to binaries:
   - **Multiple-choice → binaries:** enumerate mutually exclusive outcomes, add
     a residual "other/none" bucket so they are exhaustive, and make one binary
     per outcome. Forecast each independently; they are renormalised to sum to 1
     at aggregation (do not force it here).
   - **Numeric/date → threshold ladder:** pick 3–5 monotonic thresholds spanning
     the plausible range and write one binary per rung, e.g. P(CPI YoY > 2.5%),
     P(> 3.0%), P(> 3.5%). The ladder implies a CDF while keeping scoring binary.
2. **Force resolvability (stranger test).** Rewrite until every spec pins:
   exact metric + source of truth (e.g. "FRED CPIAUCSL, first release, not
   revised"); resolution timestamp + timezone; edge-case handling (postponement,
   ambiguity, source stops publishing → resolve **VOID**); threshold(s) for
   numeric rungs.
3. **Check for an existing market** (Manifold / Metaculus / Polymarket
   connectors) for a near-identical question. Use a found market for **exactly
   two things**: (a) adopt its battle-tested resolution wording as your source of
   truth, and (b) record its current price as a *benchmark* once the qid exists.
   Its price **must never inform the forecast** — it is not an ensemble member
   (hard rule 7). **Skip this step entirely for blind imports** (§5.13).
4. **Set the horizon.** Default 7–14 days. Warn the user if > 90 days — the
   self-improvement loop learns slowly from long horizons.
5. **Get user sign-off** on the final spec (one confirmation message), then
   create it. If a market was found, record it as a benchmark right after.

## CLI

- `oracle question create <spec.json>` — validate + store the QuestionSpec.
- `oracle baseline record <qid> market <p>` — record a found market price as a
  benchmark only (never a forecast input).
- `oracle connectors doctor` — confirm market connectors are live before the
  existing-market check.

## Failure modes / notes

- **Market price leaking into the forecast.** The found market is for wording +
  benchmark only; anchoring your probability to it destroys the signal Oracle
  measures. Blind imports must not even look it up.
- **Under-pinned resolution.** If you cannot name the exact source and timestamp,
  the stranger test fails — keep rewriting.
- **Non-exhaustive multiple-choice.** Always include the residual bucket, or the
  binaries cannot sum to 1.
- **Threshold ladder that isn't monotonic** yields an incoherent CDF — order the
  rungs and keep them nested.

See spec §5.2 (schema §7.1).
