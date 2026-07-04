---
name: update
description: Use on "update"/"check open questions" or when oracle status shows a fired trigger, to run a scoped re-forecast and append a stream point.
---

# update

Frequent small updates are a disproportionate share of the superforecaster edge,
so updating is a core workflow. Every open question is a **stream**: an ordered
series of ForecastRecords sharing a `stream_id`.

- **Trigger registry:** commits store structured triggers
  (`{type, check, due}`). `oracle triggers due` surfaces due ones; inspect a
  question's triggers with `oracle triggers check <qid>`.
- **Trigger check** (`quick` tier, no ensemble): verify whether the trigger
  fired — fetch the release, check the date, search for the event.
- **Scoped re-forecast** if fired: research restricted to what changed since the
  last stream point (view it with `oracle stream show <qid>`); reuse base rates
  and models unless invalidated; ensemble at reduced k=3 seeded with the prior
  point as an explicit anchor. Red-team question shifts to "am I over- or
  under-reacting to this news?"
- **Commit the update** as a new stream point via `oracle commit` with a
  required `update_rationale` (what changed, direction/size, fresh triggers).
  No-change updates are committed too.
- **Blind mode:** all §5.13 restrictions hold; the sealed snapshot is **not**
  refreshed (conservative — the crowd gets no updates while we do).

See spec §5.14.
