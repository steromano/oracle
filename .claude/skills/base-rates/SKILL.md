---
name: base-rates
description: Use to establish the outside-view anchor (reference classes + base rates) before any inside-view adjustment.
---

# base-rates

Outside view before inside view — anchoring on the base rate is the
highest-leverage superforecasting habit.

- **Define 1–3 candidate reference classes** (e.g. "incumbent central bank holds
  when market-implied odds of hold > 80% one week out").
- **Source base rates** in order: the `knowledge/priors/` library first, then
  historical data via connectors/search, then structured estimation if no data
  exists (state clearly that it is an estimate).
- **Record each base rate** with N (sample size), time window, and a note on
  reference-class fit.
- **Output an outside-view anchor probability** with an explicit uncertainty
  band. Record it as the `base-rate-only` baseline:
  `oracle baseline record <qid> base-rate-only <p>`.
- **Append** every new, well-sourced base rate to `knowledge/priors/` for reuse
  — this library is a compounding asset.

See spec §5.5.
