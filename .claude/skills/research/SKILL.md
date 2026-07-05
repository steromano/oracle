---
name: research
description: Use to gather dated, graded evidence via iterative agentic search once a forecast is triaged; the source of every claim in the final report.
---

# research

Agentic evidence-gathering (Halawi et al. / AIA style): iterative, not one-shot.
Establish a **dated present**, actively seek disconfirmation, prefer primary
sources, and log every claim with a grade. The single biggest LLM failure mode
is reasoning from a stale world-model, so the first job is always to pin down
the latest known state *as of today's date* with a dated source. The evidence
log this step produces is the only thing the final report is allowed to cite.

## Playbook

1. **Decompose into search intents.** Cover, with concrete query intent:
   - *Latest known state* — "as of `<today>`, current level/status of X"
     (dated). This anchors everything; do it first.
   - *Drivers for YES* — "what would push X above threshold before `<resolve>`".
   - *Drivers for NO* — "reasons X stalls / recent evidence against".
   - *Scheduled events before resolution* — releases, meetings, deadlines,
     elections that land inside the window.
   - *Expert opinion* — analyst notes, official guidance (NOT market odds; see
     blind rule below).
2. **Iterate.** Issue queries, read, refine from what you find — chase the
   thread rather than running a fixed list. Prefer primary sources (official
   statistics, filings, transcripts, registries) over commentary about them.
3. **Explicit disconfirmation pass.** Run ≥ 2 queries whose intent is to find
   evidence *against* your current leaning ("evidence X will NOT happen",
   "reasons the consensus is wrong"). Log what you find even when it survives.
4. **Log with grades.** Every claim → `data/evidence/<forecast_id>.md` with
   source URL, publication date, and an A–D relevance/reliability grade
   (A = primary/authoritative & current; D = weak/second-hand/stale). Date-stamp
   the "latest known state" line explicitly.
5. **Stop rule.** Stop when the last two searches surfaced no forecast-relevant
   update, or the effort-tier budget (from `triage`) is hit.

## CLI

- `oracle connectors doctor` — confirm data sources are live before relying on them.
- `oracle baseline record <qid> market <p>` — **non-blind questions only**, to
  log a market price as a *benchmark*. It is never a forecast input (hard rule 7).

## Failure modes / notes

- **Stale world-model** — no dated "as of today" line = the forecast is
  probably wrong. This is the top failure; guard it explicitly.
- **Confirmation-only search** — if you never logged evidence against your
  lean, the disconfirmation pass didn't happen. Redo it.
- **Blind mode** — on blind/imported questions do **not** look up the source
  platform, any prediction-market aggregator, or other markets on the same
  event, even in passing. The red-team leakage check fails a commit whose
  evidence log cites market odds on a blind question.
- **Commentary over primary** — a news article summarising a filing grades
  lower than the filing. Go to the source.

See spec §5.4.
