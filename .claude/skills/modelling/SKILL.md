---
name: modelling
description: Use for data-rich (typically finance/macro) questions to produce a probability from an explicit, simple, reproducible model.
---

# modelling

For questions with usable data, build a simple, auditable model whose output is
an advisory input to the ensemble — not an autocrat. Simplicity is a feature.

- **Pull data** via connectors into a scratch dataframe; save the *final* model
  script alongside the evidence log for reproducibility.
- **Approved v1 model classes:** empirical frequency counts; simple parametric
  fits (normal/lognormal on returns/changes); bootstrap resampling of historical
  windows; Monte Carlo over decomposed Fermi factors; logistic regression only
  if features and N justify it.
- **Every model outputs a probability *and* a sensitivity note** (which
  assumption moves the answer most).
- **Advisory, not final:** the `ensemble` skill weighs model output against the
  judgmental forecasts.

See spec §5.6.
