---
name: report
description: Use after a successful commit to render the fixed-structure forecast report for the user.
---

# report

Renders `reports/<forecast_id>.md` via `oracle report <fid>`. The structure is
**fixed** so reports are comparable over time.

- **Headline:** question, final probability, resilience grade, horizon,
  resolution date.
- **TL;DR** (≤ 5 sentences): the crux and where the probability comes from.
- **Outside view:** reference classes and anchors.
- **Inside view:** key evidence for/against, cited from the evidence log.
- **Model output** (if any) with its sensitivity note.
- **Ensemble table:** each member's probability + one-line rationale; pooled
  values; market price if any.
- **Red-team notes + update triggers** (the concrete re-forecast conditions).
  For updates, a stream-history table of prior probabilities and deltas.
- **Benchmark line:** the naive-Claude baseline for the same question, so
  harness value is eyeballable on every forecast.
- **Provenance footer:** forecast ID, commit SHA, timestamp, tools, cost.

See spec §5.10.
