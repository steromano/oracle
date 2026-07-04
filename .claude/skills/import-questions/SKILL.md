---
name: import-questions
description: Use on "import questions" to pull soon-closing platform questions in blind mode, building the resolution and calibration base.
---

# import-questions

Sources forecastable questions from Manifold/Metaculus so the ledger
accumulates resolutions fast — **without the pipeline ever seeing the market's
opinion**. Blinding is enforced in Python, not by asking you to look away.

- **Fetch candidates:** `oracle import fetch` (defaults: closes-within 14d,
  binary only, min traders/forecasters, dedupe vs `data/questions/`, exclude
  self-referential markets and configured categories). Filters run *before*
  anything reaches you.
- **Blinding at the connector layer:** you receive only title, resolution
  criteria, close date, category, platform ID. Price, community forecast,
  positions, and **comments** are stripped. The full snapshot is written to
  `data/sealed/<question_id>.json` (git-committed at import, read-only to you).
- **Spec conversion:** adopt the platform's resolution criteria verbatim; set
  `origin: import`, `blind: true`.
- **Select & queue:** present the filtered list for a one-shot approve/trim,
  then `oracle import approve` (cron uses `--auto-approve` on fetch). List
  pending with `oracle import queue`; forecast at `standard` tier.
- **Unsealing:** at `oracle commit`, the CLI copies the sealed price into the
  `market` baseline — the CLI reads `data/sealed/`, you never do.

See spec §5.13.
