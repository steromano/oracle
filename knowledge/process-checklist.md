# Process checklist (outcome-blind audit)

Run this checklist against a forecast's artifacts at commit time
(`calibrate-and-commit`, §5.9 step 3). Record the pass/fail vector to
`knowledge/audits/<forecast_id>.md` and embed it in the ForecastRecord's
`process_audit` field. Every item is **observable at forecast time** — it does
not depend on how the question resolves, which is what keeps the learning loop
(§5.12) free of "resulting".

The `retrospect` skill aggregates these vectors across forecasts to mine
recurring defects into `lessons.md`. New defect *types* are added here via
reviewed diff, so the audit gets stricter over time (the compounding
mechanism).

## Items

- [ ] **spec** — Is the question spec unambiguous? Would two strangers reading
      only the resolution criteria on resolution day agree on the outcome?
- [ ] **latest-known-state** — Is the latest known state of the world
      established explicitly, with a **dated** source? (Reasoning from a stale
      world-model is the most common LLM forecasting error.)
- [ ] **scheduled-events** — Have all scheduled, forecast-relevant events
      between now and the resolution deadline been checked (release calendars,
      meetings, deadlines)?
- [ ] **disconfirmation** — Was a disconfirmation pass done — at least two
      queries explicitly seeking evidence *against* the current leaning?
- [ ] **arithmetic** — Was all recombination/decomposition arithmetic verified
      in Python (via the CLI), not in prose? Coherence checks pass
      (P(A)+P(¬A)=1; threshold ladders monotone)?
- [ ] **evidence-dates** — Are all evidence-log item publication dates sane and,
      for frozen/`info_cutoff` questions, strictly before the cutoff (no
      leakage)?
- [ ] **base-rates** — Was an outside-view anchor (reference class + base rate
      with N) established before the inside view?
- [ ] **triggers** — Does the commit carry ≥ 1 concrete, checkable update
      trigger (≥ 3 if resilience is `fragile`)?
- [ ] **blinding** (blind imports only) — Does the evidence log contain **no**
      market-odds citations? Direct market lookups are a hard commit failure.
