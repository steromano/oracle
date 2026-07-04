---
name: resolve
description: Use when the user says "resolve" or oracle status shows due forecasts, to determine outcomes and record scored ResolutionRecords.
---

# resolve

Resolves due forecasts against their spec's source of truth and records scored
outcomes. A single shocking miss does **not** trigger a special postmortem —
that is the "resulting" reflex §5.12 suppresses; it just counts toward the next
scheduled review.

- **List due:** `oracle status` (or `oracle resolve --due`) lists due forecasts;
  load each QuestionSpec's resolution criteria.
- **Determine the outcome** using the specified source of truth (fetch the FRED
  series, check the market's resolution, search the named source). Imported
  questions are easy: read the platform's own resolution via the connector
  (inherit VOID if the platform N/A's the market).
- **The bar is the criteria as written.** If genuinely ambiguous, resolve VOID
  and write a spec-defect audit entry (§5.12) — spec defects are the most
  valuable process lessons.
- **Record:** `oracle resolve <fid> --outcome yes|no|void --evidence <url/note>`
  — writes the ResolutionRecord and computes time-averaged stream scores for the
  system *and all logged baselines*.
- **Cadence:** trigger `retrospect` every 10 resolutions.

See spec §5.11.
