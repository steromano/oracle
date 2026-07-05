---
name: update
description: Use on "update"/"check open questions" or when oracle status shows a fired trigger, to run a scoped re-forecast and append a stream point.
---

# update

Frequent small updates are, per Tetlock, a disproportionate share of the
superforecaster edge — so updating is a core workflow, not a nicety. Every open
question is a **stream**: an ordered series of committed ForecastRecords sharing
a `stream_id`, scored by time-averaged Brier. (Not yet exercised.)

## Playbook

1. **Trigger registry:** `oracle triggers due` surfaces due update triggers
   exactly the way `oracle status` surfaces due resolutions; inspect a specific
   question with `oracle triggers check <qid>`.
2. **Trigger check (`quick` tier, no ensemble):** verify whether the trigger
   actually fired — fetch the release, check the date, search for the event.
   Stop here if it didn't fire and nothing material changed.
3. **Scoped re-forecast (if fired):** research restricted to *what changed* since
   the last stream point (`oracle stream show <qid>`); reuse base rates and
   models unless invalidated; run a reduced ensemble (k = 3) seeded with the
   prior stream point as an explicit anchor to move *from*.
4. **Red-team shifts** to "am I over- or under-reacting to this news?" —
   under-reaction is the human default, over-reaction the LLM-recency default.
5. **Commit the update** as a new stream point via `oracle commit` with a
   required `update_rationale` (what changed, direction and size of move) plus
   fresh triggers. **No-change updates are committed too** — a re-affirmed
   probability after checked evidence is information, and time-averaged scoring
   credits it. The committed number comes only from your own reasoning.

## CLI

`oracle triggers due` · `oracle triggers check <qid>` · `oracle stream show <qid>`
· `oracle commit <forecast.json> [--dry-run]`

## Failure modes / notes

- **Blind mode:** keep all §5.13 sourcing restrictions, and do **not** refresh
  the sealed snapshot — the benchmark stays anchored at import time (conservative
  against us: the crowd gets no updates while we do).
- The market is a **benchmark only**, never an ensemble member. For non-blind
  questions the market baseline may be re-sampled per update for a fair
  stream-vs-stream comparison; the naive-Claude baseline stays a single constant
  point (that's the point of the comparison).
- Don't re-run full research or a full ensemble — the discipline is *scoped*.

See spec §5.14.
