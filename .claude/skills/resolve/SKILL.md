---
name: resolve
description: Use when the user says "resolve" or oracle status shows due forecasts, to determine outcomes and record scored ResolutionRecords.
---

# resolve

Settles due forecasts against their QuestionSpec's declared source of truth and
records scored `ResolutionRecord`s. Resolution is a **determination**, not a
re-forecast: read the specified source, apply the criteria exactly as written,
record. The CLI then computes time-averaged stream scores for Oracle **and every
logged baseline** (naive-claude, base-rate-only, market) on that question.

## Playbook

1. **List what's due.** `oracle status` (or `oracle resolve --due`) reports due
   forecasts. Work them one at a time.
2. **Load the resolution criteria** from each QuestionSpec, plus the named
   source of truth (FRED series, the platform's own resolution, the specific
   named source).
3. **Determine the outcome from that source only.**
   - *Imported / blind questions are the easy case:* read the platform's own
     resolution via the connector. Inherit **VOID** if the platform N/A's or
     annuls the market.
   - *Own questions:* fetch the specified source and apply the criteria as
     written. The bar is the wording, not your judgment of what "should" count.
4. **Ambiguous criteria ⇒ resolve VOID.** If the criteria as written cannot be
   applied unambiguously to the observed world, resolve `void` and write a
   **spec-defect audit** to `knowledge/audits/<fid>.md` (§5.12). VOID means the
   *spec* was defective — this write-up is the most valuable process lesson
   resolve produces, and the only per-question postmortem that is warranted.
   VOID is *only* for defective specs, never for hiding an embarrassing miss.
5. **Record it.** `oracle resolve <fid> --outcome yes|no|void --evidence <note>`
   — cite the source (URL / series value / platform resolution) in the note.
   This writes the ResolutionRecord and scores Oracle and all baselines.
6. **Cadence.** After every ~10 resolutions, run `retrospect`. Do **not** launch
   a special postmortem on a single shocking miss — that is the "resulting"
   reflex §5.12 suppresses; one surprising outcome just counts toward the next
   scheduled review.

## CLI

`oracle status` · `oracle resolve --due` (list) · `oracle resolve <fid>
--outcome yes|no|void --evidence <note>` · `oracle resolve --platform-only`
(cron auto-resolve of imported questions). Then `retrospect` every ~10.

## Failure modes / notes

- **Determination, not forecasting.** Never re-open the reasoning or adjust a
  probability at resolution time; you only read the outcome and record it.
- **Outcome-blind boundary.** Resolving records the outcome; it does *not* mine
  lessons from whether Oracle was right or wrong. Narrative learning happens in
  `retrospect`, from outcome-blind commit-time audits — not here.
- **Score all baselines.** The point of the exercise is measuring harness value,
  so every logged baseline is scored on the same resolution; do not resolve in a
  way that skips them.
- Let the CLI do all scoring and date math — never compute a Brier score or a
  due date by hand.

See spec §5.11.
