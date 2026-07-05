---
name: calibrate-and-commit
description: Use as the final forecasting step to apply the calibration map, run the outcome-blind process audit, and log the ForecastRecord via the CLI.
---

# calibrate-and-commit

The gate before the user sees a number. Nothing is stated until `oracle commit`
succeeds — the CLI stamps `committed_at`, the git SHA, and the evidence hash, so
you cannot backdate or forge them. This skill turns the red-teamed probability
into a logged ForecastRecord.

## Playbook

1. **Apply the active calibration map, if one exists.** Run
   `oracle calibration show`. A map is a monotone transform fitted on ≥ 50
   resolved forecasts (typically mild extremization — LLMs are underconfident).
   If none is active yet (too few resolutions), this step is a no-op — proceed.
2. **Enforce floors/ceilings.** Keep the probability in [0.01, 0.99] absent
   written extraordinary justification (log-score protection). The CLI clamps
   too, but do it deliberately.
3. **Verify benchmarks are recorded** (market-independence). Confirm the
   naive-Claude baseline and the base-rate-only anchor are logged, and — if a
   market exists for a non-blind question — that its price is recorded as a
   **benchmark** (`oracle baseline record <qid> market <p>`). The market is
   never a forecast input; it is only there to measure harness value. A missing
   benchmark is a fixable gap, so record it before committing.
4. **Outcome-blind process audit.** Run `knowledge/process-checklist.md` against
   this forecast's artifacts (spec resolvable? latest-known-state dated?
   scheduled events checked? disconfirmation pass done? arithmetic verified in
   Python? evidence dates sane?). Write the pass/fail vector to
   `knowledge/audits/<forecast_id>.md` and embed it in the record. This audit —
   not resolution-day postmortems — is the raw material for the learning loop.
5. **Set update triggers.** ≥ 1 concrete, checkable trigger (a date, a data
   release, a market-move threshold — never "if something big happens"); **≥ 3
   if the resilience grade is `fragile`**.
6. **Commit.** `oracle commit <forecast.json> --dry-run` first to validate, then
   without the flag to write. Only after a successful commit is the report
   rendered (`report` skill).

## CLI

`oracle calibration show` · `oracle baseline record <qid> market <p>` ·
`oracle commit <forecast.json> [--dry-run]`.

## Failure modes / notes

- **No calibration map exists until ≥ 50 resolutions** — expect step 1 to be a
  no-op early on; that is correct, not an error.
- Never fold the market into the committed probability. An optional, clearly
  labelled Oracle+market blend may be reported as decision support, but it is
  not the committed number.
- Writing the audit after peeking at any outcome breaks the outcome-blind
  guarantee — audits are written from artifacts only.
- A vague trigger fails validation; make each one machine-checkable by
  `oracle triggers`.
- If red-team proposed a > ±10-point move, do not commit — the flow should have
  looped back to research.

See spec §5.9.
