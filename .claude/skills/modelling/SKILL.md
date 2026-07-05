---
name: modelling
description: Use for data-rich (typically finance/macro) questions to produce a probability from an explicit, simple, reproducible model.
---

# modelling

For questions with usable data (mostly finance/macro), build a simple, auditable
model whose output is an *advisory input* to the ensemble — never the final word.
Simplicity is the feature: a model you can re-run and explain beats a clever one
you can't. Skip this skill entirely when there's no data to model.

## Playbook

1. **Pull data** via connectors into a scratch dataframe in the per-forecast
   scratch dir. Note the source, series, and as-of date.
2. **Pick the simplest fitting model class** (v1 approved list):
   - empirical frequency counts (how often did the thing happen historically);
   - simple parametric fits — normal/lognormal on returns or level changes;
   - bootstrap resampling of historical windows;
   - Monte Carlo over decomposed Fermi factors;
   - logistic regression *only* if feature count and N genuinely justify it.
   When two classes fit, prefer the one with fewer free parameters.
3. **Emit a probability + a one-line sensitivity note** — which single
   assumption (window length, distribution choice, a Fermi factor) moves the
   answer most, and by roughly how much.
4. **Save the *final* model script** alongside the evidence log so the run is
   reproducible; delete throwaway exploration.
5. **Hand the probability to `ensemble`** as one method-member (the statistical
   pass). It is weighed against judgmental members, not treated as ground truth.

## CLI

- All data lands on disk via connectors, not the `oracle` CLI; sanity-check them
  first with `oracle connectors doctor`.
- The model's probability enters the ensemble pool through
  `oracle aggregate --probs ...` (in the `ensemble` skill), and can be logged as
  a named baseline: `oracle baseline record <qid> model <p>`.

## Failure modes / notes

- **Overfitting theatre** — a model with more knobs than data points is a
  judgment call in disguise. Fewer parameters, wider bands.
- **Regime blindness** — historical frequencies assume the past regime holds;
  say so in the sensitivity note when it plausibly doesn't.
- **Silent staleness** — always record the data as-of date; a model on stale
  series is worse than no model.
- **Autocrat drift** — never let a precise-looking model number override the
  ensemble; it is one member.

See spec §5.6.
