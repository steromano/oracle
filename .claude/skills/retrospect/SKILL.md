---
name: retrospect
description: Use every ~10 resolutions (or on "review performance") to mine outcome-blind process lessons and run the statistical calibration review.
---

# retrospect

The self-improvement loop. Design principle: **learn from process, calibrate
from outcomes — and mostly don't learn from misses.** Two decoupled channels.

**Channel 1 — process (textual, outcome-blind).**
- Raw material: the commit-time audit vectors against
  `knowledge/process-checklist.md`.
- Aggregate audits across recent forecasts; find *recurring* defects (spec
  ambiguity, missed scheduled events, stale state, skipped disconfirmation,
  unverified arithmetic, evidence-date problems).
- **Distil lessons** into `knowledge/lessons.md` — valid only if actionable,
  general, and tagged to a defect observable at forecast time (never a
  surprising outcome).
- **Extend the checklist** with genuinely new defect *types* (reviewed diff).
- **Propose system diffs** (SKILL.md / priors / CLAUDE.md) as git diffs for
  human review. Outcomes may inform *prioritisation* only, never generate
  lessons.

**Channel 2 — outcomes (statistical, automated).**
- Review the scoreboard segments: `oracle scoreboard --segment domain`.
- If ≥ 50 resolutions since the last fit: `oracle calibration fit`, check it
  improves backtested Brier, then `oracle calibration activate <id>`.

VOIDs are the one per-question write-up (a defective spec is a process defect).

See spec §5.12.
