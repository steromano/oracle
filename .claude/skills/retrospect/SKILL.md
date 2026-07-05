---
name: retrospect
description: Use every ~10 resolutions (or on "review performance") to mine outcome-blind process lessons and run the statistical calibration review.
---

# retrospect

The self-improvement loop, run every ~10 resolutions. Design principle: **learn
from process, calibrate from outcomes — and mostly don't learn from misses.** At
hobby volumes an individual outcome is nearly pure noise about reasoning quality,
so lessons are mined from outcome-blind process audits; outcomes only feed the
statistical recalibration fit. Two decoupled channels. (Not yet exercised — needs
~10 resolutions before the first real run.)

## Playbook

**Channel 1 — process (textual, outcome-blind).** Do this *without* looking at
any outcome.
1. Gather the raw material: aggregate the commit-time process-audit vectors in
   `knowledge/audits/` across recent forecasts.
2. Find *recurring* defects — spec ambiguity, missed scheduled events, stale
   latest-known-state, skipped disconfirmation, unverified arithmetic,
   evidence-date problems. A one-off is not a lesson; a repeated pattern is.
3. Distil lessons into `knowledge/lessons.md`. A lesson is valid only if it is
   (a) actionable, (b) general beyond one question, and (c) tagged to a process
   defect observable *at forecast time*. "For central-bank questions, check the
   official communications calendar to resolution" is valid; "be more bullish on
   incumbents" from a couple of misses is not.
4. Extend `knowledge/process-checklist.md` with genuinely new defect *types*
   (reviewed diff). This is the compounding mechanism — the commit-time audit
   gets stricter over time.
5. Draft any implied skill / CLAUDE.md / priors changes as git diffs for human
   review. The system edits itself only through reviewed commits.

**Channel 2 — outcomes (statistical).**
6. Review scoreboard segments: `oracle scoreboard --segment domain`. Miscalibration
   and domain weakness are statistical claims, not narratives.
7. If ≥ 50 resolutions since the last fit: `oracle calibration fit`, confirm it
   improves backtested Brier (`oracle calibration show`), then
   `oracle calibration activate <id>`.

**Cross-channel:** outcomes may be consulted for exactly one thing —
*prioritising* which recurring defect to fix first (the one co-occurring with the
worst scores). They never generate a lesson.

**VOIDs** are the one exception that warrants a per-question write-up: a VOID means
the spec was defective (a process defect), so it gets an entry in
`knowledge/audits/` plus a checklist-extension proposal.

## CLI

`oracle scoreboard --segment domain` · `oracle calibration fit` ·
`oracle calibration show` · `oracle calibration activate <id>`

## Failure modes / notes

- **Resulting is the enemy.** Never write a lesson from how the coin landed; a
  single shocking miss is not a postmortem trigger, it just counts toward the
  next scheduled review.
- Don't bloat the checklist with question-specific noise — add only new defect
  *types*.
- Calibration fit is meaningless below N ≥ 50; don't activate a map that doesn't
  beat the current backtested Brier.

See spec §5.12.
