---
name: import-questions
description: Use on "import questions" to pull soon-closing platform questions in blind mode, building the resolution and calibration base.
---

# import-questions

Sources binary questions from Manifold/Metaculus so the ledger accumulates
resolutions fast — **without the pipeline ever seeing the market's opinion**.
Blinding is enforced at the connector layer (in Python), not by asking you to
look away. This is the bootstrapping and calibration engine. Exercised once and
working.

## Playbook

1. **Fetch candidates:** `oracle import fetch --platform manifold,metaculus
   --closes-within 14d --max 20`. Deterministic quality filters run *before*
   anything reaches the LLM: binary only; unambiguous, non-self-referential
   criteria; `--min-traders` (Manifold, default ≥ 30) / `--min-forecasters`
   (Metaculus, default ≥ 20); configured category exclusions (e.g. sports);
   dedupe vs `data/questions/`. Scheduled runs add `--auto-approve` (safe
   because filtering is deterministic).
2. **Blinding at the connector layer.** You receive only: title, resolution
   criteria, close date, category, platform question ID. Price, community
   forecast, positions, and **comments** are stripped before the payload enters
   context. The full snapshot is sealed to `data/sealed/<question_id>.json`,
   git-committed at import (provably captured *before* the forecast) and readable
   by the CLI only — never by you.
3. **Spec conversion:** adopt the platform's resolution criteria verbatim; set
   `origin: import`, `blind: true`, platform resolution as the source.
4. **Select & queue:** present the filtered list for a one-shot approve/trim,
   then `oracle import approve`. List pending with `oracle import queue`. Queued
   imports are forecast in normal pipeline runs at `standard` tier; the naive
   baseline is elicited there pre-research as usual.
5. **Unsealing at commit:** `oracle commit` copies the sealed price into the
   `market` benchmark for that question (the CLI reads `data/sealed/`; you still
   don't). This yields a clean, independent Oracle-vs-crowd comparison — large N,
   fast resolution, untainted benchmark.

## CLI

`oracle import fetch [--platform --closes-within --max --min-traders
--min-forecasters --auto-approve]` · `oracle import approve` ·
`oracle import queue` · `oracle connectors doctor`

## Failure modes / notes

- **Metaculus now needs an API token** (`METACULUS_API_TOKEN`) and changed its
  schema; if fetch errors, check the token and run `oracle connectors doctor`.
  Manifold works unauthenticated.
- Never read `data/sealed/` yourself, and never look up the market (or any
  aggregator) for a blind question — the red-team leakage check fails the commit
  if market odds appear in the evidence log.
- The market is a **benchmark only**, never an ensemble member (true for every
  question). Blind imports go further: the price stays sealed and unread until
  `oracle commit` unseals it into the `market` benchmark after the forecast.

See spec §5.13.
