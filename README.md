# Oracle

A self-improving LLM forecasting harness. Oracle keeps the **measurement loop**
— ledger → resolve → score — airtight in deterministic, fully-tested Python, and
leaves *judgment* to Claude Code driving markdown skills.

The architecture is a strict split (spec §3.1): all math, storage, dates, and
scoring live in the pure `src/oracle/` package, reachable only through the
`oracle` CLI. State is git-tracked JSON on disk (an append-only ledger). The LLM
never edits `data/` directly and never reads `data/sealed/` — blinding is
enforced in Python, not in prompts.

- **A forecast that isn't logged doesn't exist.** Nothing is "forecast" until
  `oracle commit` succeeds and writes a record.
- **Deterministic plumbing, LLM judgment.** Import fetching, scoring,
  resolution, and reporting are pure CLI. Only the reasoning is the model's job.

---

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 (uv fetches it for
you; the system Python may be newer and is not used).

```bash
uv python pin 3.12
uv sync --extra dev
```

Verify the toolchain and run the test suite:

```bash
uv run python -c "import sys; print(sys.version)"   # 3.12.x
uv run pytest -q
```

Copy the secrets template and fill in whatever you have (every connector
degrades gracefully when its key is absent):

```bash
cp .env.example .env
```

The CLI is invoked as `uv run oracle <subcommand>`. See the full command surface
with `uv run oracle --help`.

---

## Worked example (end to end)

This walks a single question from creation through a rendered report,
resolution, and the scoreboard. Every timestamp, ID, and git SHA is stamped by
the CLI — you never supply them, so the model can't backdate a forecast.

### 0. Start of session

Always begin by asking Oracle what needs attention:

```bash
uv run oracle status
```

On a fresh repo this reports an empty ledger and exits `0`. When resolutions or
triggers are due it prints them and exits `10` ("attention needed") so
automation can decide whether to page a human.

### 1. Create the question

Write a `QuestionSpec` (the CLI stamps `id` and `created_at`):

```json
{
  "title": "RBA holds cash rate in August 2026",
  "question_text": "Will the RBA leave the cash rate unchanged at its August 2026 meeting?",
  "q_type": "binary",
  "resolution_criteria": "Resolves YES if the post-meeting statement keeps the cash rate target unchanged from July.",
  "resolution_source": "https://www.rba.gov.au/media-releases/",
  "resolution_deadline": "2026-08-12T05:00:00Z",
  "edge_cases": "An unscheduled inter-meeting move before the August meeting resolves NO.",
  "domain": "macro",
  "horizon_days": 38,
  "origin": "user",
  "created_by": "stefano"
}
```

```bash
uv run oracle question create question.json     # -> Created Q-YYYYMMDD-001
```

### 2. Log the naive baseline first (before any research)

This is the central control — *does the harness beat just asking Claude?* Elicit
it before research so it can't be contaminated:

```bash
uv run oracle baseline record Q-20260705-001 naive-claude 0.62
```

### 3. Commit the forecast

Write a `ForecastRecord`. Omit `id`, `stream_*`, `committed_at`, and `git_sha`
— the CLI assigns them. The probability is clamped to `[0.01, 0.99]`, and at
least one update trigger is required (three if `resilience` is `fragile`):

```json
{
  "question_id": "Q-20260705-001",
  "probability": 0.70,
  "raw_pool": {"median": 0.70, "trimmed": 0.69, "geo_odds": 0.71},
  "ensemble": [
    {"kind": "method:base-rate", "probability": 0.66, "crux": "RBA holds at ~2/3 of meetings post-tightening."},
    {"kind": "evidence-slice:inflation-print", "probability": 0.74, "crux": "Latest CPI in the target band."}
  ],
  "pool_method": "median",
  "resilience": "moderate",
  "ensemble_iqr": 0.05,
  "process_audit": {"naive_baseline_first": true, "read_lessons": true},
  "effort_tier": "standard",
  "tools_used": ["base-rates", "asknews"],
  "evidence_log": "See knowledge/evidence/Q-20260705-001.md",
  "evidence_hash": "sha256:abc123",
  "update_triggers": [
    {"type": "release", "check": "August CPI print", "due": "2026-08-05T00:00:00Z"},
    {"type": "date", "check": "Re-check 48h before the meeting", "due": "2026-08-10T05:00:00Z"}
  ]
}
```

Dry-run first (validates and stamps, writes nothing), then commit for real:

```bash
uv run oracle commit forecast.json --dry-run     # prints the stamped record
uv run oracle commit forecast.json               # -> Committed F-YYYYMMDD-001
```

You can inspect the probability time series at any point:

```bash
uv run oracle stream show Q-20260705-001
```

### 4. Render the report

```bash
uv run oracle report F-20260705-001              # -> reports/F-20260705-001.md
```

The report has a fixed structure (headline probability, resilience grade,
ensemble table, update triggers, and the naive-claude benchmark line) so reports
are comparable over time. Dates render in Australia/Sydney.

### 5. Resolve when the deadline arrives

```bash
uv run oracle resolve F-20260705-001 --outcome yes --evidence "https://www.rba.gov.au/media-releases/2026/mr-26-XX.html"
```

This writes a `ResolutionRecord` and recomputes Brier / stream-Brier / log
scores for the system **and every logged baseline**, plus paper-trading P&L
against the market baseline where one exists. Use `--outcome void` for a
defective spec.

### 6. Read the scoreboards

```bash
uv run oracle scoreboard                          # accuracy vs baselines (§9.4)
uv run oracle pnl                                 # paper-trading track (§9.4)
```

Both are honest about small samples: any segment with **N < 30** prints
`insufficient N`, and headline comparisons ship a bootstrap confidence interval.
Add `--render` to write `reports/scoreboard.md` / `reports/pnl.md`.

### Blind imports (optional)

Instead of hand-writing questions you can pull soon-closing market questions,
stripped of price/crowd data before they reach the model:

```bash
uv run oracle import fetch --platform manifold,metaculus --closes-within 14d --max 20
uv run oracle import approve --all                # seal snapshots + create specs
uv run oracle import queue                         # list queued, unforecast imports
```

When you later `oracle commit` a forecast for an import question, the CLI
unseals the crowd price into the `market` baseline automatically — the CLI reads
`data/sealed/`, the model never does. That gives a genuinely independent
Oracle-vs-crowd head-to-head on the scoreboard.

Check which connectors are live (no secret values are printed):

```bash
uv run oracle connectors doctor
```

---

## Enabling the GitHub Actions automation

Oracle runs on GitHub Actions at three levels (spec §11). Level 1 ships enabled;
Level 2 ships disabled.

### Level 1 — cron the plumbing (`.github/workflows/oracle-cron.yml`, enabled)

Runs nightly at **03:00 Australia/Sydney** plus on-demand
(`workflow_dispatch`). It is **pure CLI, zero LLM cost**: fetch + seal imports,
check triggers, resolve platform-resolvable imports, rebuild the scoreboard and
P&L, commit + push state with an `[oracle-cron]` message, and notify a webhook.
Silence means nothing needs a brain.

To wire notifications, add a repo secret **`ORACLE_WEBHOOK_URL`** (a Slack
incoming-webhook URL or email relay). Optional connector keys
(`FRED_API_KEY`, `ASKNEWS_CLIENT_ID`, `ASKNEWS_CLIENT_SECRET`) are read from repo
secrets if present. The workflow **asserts `ANTHROPIC_API_KEY` is absent** before
running — Level 1 never touches the LLM, and a stray key could silently bill the
API account (§11.2).

### Level 2 — scheduled brain (`.github/workflows/oracle-brain.yml`, disabled)

Runs Claude Code itself via the official `anthropics/claude-code-action` with a
fixed prompt (resolve what needs judgment, run updates for fired triggers,
forecast the queue, commit state), hard-capped at **5 forecasts per run**.

It is **`workflow_dispatch`-only** as shipped — the `schedule:` trigger is
commented out. Hold it off for the first ~2 months (§11.4); flip it on only when
the queue is chronically backed up because nobody opened Claude Code.

To enable Level 2:

1. Generate a subscription token locally and store it as a repo secret so runs
   draw on your Claude Pro/Max quota rather than per-token API billing:

   ```bash
   claude setup-token
   ```

   Save the value as the repo secret **`CLAUDE_CODE_OAUTH_TOKEN`**. The token is
   single-user; size the schedule for one maintainer.

2. **Never set `ANTHROPIC_API_KEY`** in this repo's Actions environment. If both
   credentials are reachable, headless runs can silently bill the API account per
   token — the workflow asserts the key is absent and fails fast if it isn't.

3. Test it by hand from the Actions tab ("Run workflow"), then uncomment the
   `schedule:` block in `oracle-brain.yml` to turn it on.

Both workflows share the `oracle-state` concurrency group
(`cancel-in-progress: false`) so cron and brain runs never interleave commits,
and both `git pull --rebase` before pushing. The append-only ledger (new files
only) makes conflicts near-impossible.

---

## Adding a domain skill (for the collaborator)

Forecasting judgment lives in markdown skills under `.claude/skills/<name>/`,
loaded by `CLAUDE.md`. To add domain expertise (say a `macro-rates` playbook):

1. Create `.claude/skills/macro-rates/SKILL.md` with YAML frontmatter:

   ```markdown
   ---
   name: macro-rates
   description: Base rates and cruxes for central-bank rate-decision questions.
   ---

   ## Purpose
   How to forecast rate-decision questions: which base rates to pull, which
   releases move them, and the usual cruxes.

   ## Steps
   - Pull the meeting-by-meeting hold/move base rate for the relevant era.
   - Fold in the latest inflation and labour prints as evidence slices.
   - Register update triggers on the next CPI print and 48h before the meeting.

   See spec §5.x for the stage this plugs into.
   ```

2. Keep it a **stub, not a full essay** — one-paragraph purpose, the numbered
   steps compressed to bullets, and a pointer to the relevant spec section. The
   generic forecasting stages already live in the 13 shipped skills; a domain
   skill only adds what's specific to that domain.

3. Reference real `oracle` subcommands only (`uv run oracle --help` is the source
   of truth). The skill never edits `data/` directly and never reads
   `data/sealed/` — all state changes go through the CLI.

4. Commit the new skill. On the next session Claude Code picks it up via
   `CLAUDE.md`'s routing.

---

## Layout

```
src/oracle/         deterministic package (models, scoring, ledger, CLI, ...)
  cli.py            the only sanctioned path to on-disk state
.claude/            CLAUDE.md orchestrator + skills + settings
data/               git-tracked JSON state (ledger, questions, sealed, benchmarks)
reports/            rendered forecast reports + scoreboards
.github/workflows/  oracle-cron.yml (L1, on) + oracle-brain.yml (L2, off)
forecasting-harness-spec.md   the authoritative design
```
