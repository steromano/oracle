---
name: ensemble
description: Use to run k independent forecasting passes diversified by inputs/methods, reconcile disagreement, and pool into a single probability with a resilience grade.
---

# ensemble

Keeps AIA's ensemble + supervisor structure, but sources diversity from
**inputs and methods, not personas** — multiple prompt personalities on the same
model reading the same evidence produce correlated errors dressed as
disagreement (§2.2).

- **Spawn k independent passes** (k from effort tier), diversified along real
  axes: **evidence partition** (disjoint/overlapping slices; one control member
  gets the full log), **method** (≥ 1 statistical model output when available,
  one base-rate-only, one news-only), and optionally **model** (one non-Claude
  pass via OpenRouter). Each returns probability + 3-line rationale + key crux;
  run as subagent tasks.
- **Supervisor reconciliation:** if max pairwise spread > 15 pts, identify the
  crux, commission one targeted research task, re-elicit from divergent members.
  One reconciliation round max.
- **Pool** with `oracle aggregate --probs 0.6,0.7,0.55` (default median; also
  record trimmed mean and geo-mean-of-odds). Include a liquid market price as a
  one-agent-weight member **only if the question is not blind**.
- **Resilience:** record ensemble IQR + expected news before resolution → a
  coarse grade (robust / moderate / fragile). Fragile forecasts get tighter
  triggers.

See spec §5.7.
