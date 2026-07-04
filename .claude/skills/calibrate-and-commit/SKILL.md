---
name: calibrate-and-commit
description: Use as the final forecasting step to apply the calibration map, run the outcome-blind process audit, and log the ForecastRecord via the CLI.
---

# calibrate-and-commit

The gate before the user sees a number. Nothing is stated until `oracle commit`
succeeds — the CLI stamps the timestamp and git SHA, so you cannot backdate.

- **Apply the recalibration map** if one is active (`oracle calibration show`):
  a monotone transform fitted on ≥ 50 resolved forecasts correcting measured
  miscalibration (typically mild extremization — LLMs are underconfident).
- **Enforce floors/ceilings:** nothing outside [0.01, 0.99] without written
  extraordinary justification. (The CLI also clamps.)
- **Outcome-blind process audit:** run `knowledge/process-checklist.md` against
  this forecast's artifacts; write the pass/fail vector to
  `knowledge/audits/<forecast_id>.md` and embed it in the record. This audit —
  not resolution-day postmortems — is the raw material for the learning loop.
- **Update triggers are mandatory:** ≥ 1 concrete, checkable trigger (date, data
  release, market-move threshold); ≥ 3 if the grade is `fragile`.
- **Commit:** `oracle commit <forecast.json>` (use `--dry-run` first to
  validate). Only after a successful commit is the report rendered.

See spec §5.9.
