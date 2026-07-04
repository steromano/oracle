---
name: research
description: Use to gather dated, graded evidence via iterative agentic search once a forecast is triaged; the source of every claim in the final report.
---

# research

Agentic evidence-gathering adapted from Halawi et al. and AIA — iterative, not
one-shot retrieval. Establish the present, seek disconfirmation, and log
everything with dates.

- **Decompose into search intents:** status quo, drivers for YES, drivers for
  NO, scheduled events before resolution, expert/market opinions.
- **Iterative agentic search:** issue queries, read, refine based on findings.
  Prefer primary sources (official stats, filings, transcripts) over commentary.
- **Evidence-log discipline:** every claim → `data/evidence/<forecast_id>.md`
  with source URL, publication date, and an A–D relevance/reliability grade. The
  report cites only from this log.
- **Recency:** explicitly establish "latest known state as of today" with a
  dated source — the top LLM failure mode is a stale world-model.
- **Disconfirmation pass:** ≥ 2 queries explicitly seeking evidence *against*
  the current leaning.
- **Stop rule:** stop when the last two searches surfaced no relevant update, or
  the effort-tier budget is hit.
- **Blind mode:** never fetch the source platform's page, any prediction-market
  aggregator, or other markets on the same event.

See spec §5.4.
