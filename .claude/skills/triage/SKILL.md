---
name: triage
description: Use right after question-intake to set the effort budget, route, tool plan, and leakage flag for a forecast.
---

# triage

A cheap, **mandatory** classification step that runs right after
question-intake and before any expensive skill. It is fast (seconds of
judgment, no research) — but it must actually be done and its four decisions
**stated explicitly**. Do not silently default to `standard`: skipping triage
was the top process gap in early runs.

## Playbook

State all four of the following, out loud, before proceeding:

1. **Route** — `stat-model` (recurring data series → `modelling` is primary),
   `judgmental` (one-off event → `research` is primary), or `hybrid` (both).
2. **Effort tier** —
   - `quick`: 1 research agent, no ensemble (trivial / low-stakes);
   - `standard` (default): full pipeline, 3-member ensemble;
   - `deep`: 5-member ensemble, supervisor round, extra red-team pass
     (high-stakes, contested, or long-horizon).
3. **Tool plan** — which connectors this question needs (e.g. FRED for macro;
   market connectors only for the wording/benchmark step, never as a forecast
   input). Confirm they are live with `oracle connectors doctor`.
4. **Leakage-risk flag** — is the answer already *determined but unindexed*
   ("did X happen yesterday")? If so this is **lookup, not forecasting**: answer
   directly and do **not** commit it to the ledger. Also flag blind questions
   (§5.13) here so downstream skills honour the sourcing restriction.

Then, before research begins, elicit the **naive-Claude baseline** from a clean
subagent (fresh context — no tools, evidence, or lessons) using **exactly**:

> Think like a superforecaster and answer with a probability. [question spec]

and record it. Eliciting it now prevents contamination from research context.

## CLI

- `oracle connectors doctor` — verify the tool plan's connectors are live.
- `oracle baseline record <qid> naive-claude <p>` — log the pre-research
  naive baseline.

## Failure modes / notes

- **Skipping triage / implicit `standard`.** The most common early miss. It is
  cheap; do it and state the four decisions every time.
- **Mis-routing.** A data-rich series sent down the judgmental path (or vice
  versa) wastes the whole run — pick the primary skill deliberately.
- **Missing the leakage flag.** Forecasting an already-decided event pollutes
  calibration; catch it here, not at red-team.
- **Market as a tool-plan input.** Connectors may confirm a market for wording
  and benchmarking only — the price is never a forecast input (hard rule 7).

See spec §5.3.
