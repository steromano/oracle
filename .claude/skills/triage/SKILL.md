---
name: triage
description: Use right after question-intake to set the effort budget, route, tool plan, and leakage flag for a forecast.
---

# triage

Cheap classification step that sets the effort budget and the route before the
expensive skills run.

- **Type:** stat-model-friendly (recurring data series → `modelling` primary) vs
  judgmental (one-off event → `research` primary) vs hybrid.
- **Effort tier:** `quick` (1 research agent, no ensemble — trivial/low-stakes);
  `standard` (default: full pipeline, 3-member ensemble); `deep` (5-member
  ensemble, supervisor round, extra red-team pass).
- **Tool plan:** which connectors are relevant (FRED for macro, market
  connectors for anything with a listed market). Check liveness with
  `oracle connectors doctor`.
- **Leakage-risk flag:** if the answer may already be determined-but-unindexed
  ("did X happen yesterday"), that's lookup, not forecasting — answer directly
  and do **not** pollute the ledger.

See spec §5.3.
