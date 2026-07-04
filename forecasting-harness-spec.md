# Oracle: technical spec for a self-improving LLM forecasting harness

**Status:** Draft v1.1 — for handover to a coding agent
**Author:** Stefano Romano (spec drafted with Claude)
**Date:** 4 July 2026
**Target runtime:** Claude Code, Python 3.12+
**v1.1 changes:** forecast streams as the core object; paper-trading P&L scoring track; input-based ensemble diversity; process-audit learning loop; resilience metric; loop-first build strategy. Deviations from the literature are catalogued in §2.4.

---

## 1. Purpose and product definition

Oracle is a self-contained repository that turns Claude Code into a judgmental forecasting system. The UX contract is:

> Open Claude Code in the repo → ask a forecasting question in natural language → receive a structured forecasting report with a calibrated probability (or distribution), full reasoning trace, and a logged forecast that the system will later resolve and score itself.

Beyond producing individual forecasts, the system is a *learning loop*: every forecast is recorded in a ledger, resolved when its resolution date arrives, scored against benchmarks (including a "naive Claude" baseline answering the same question without the harness), and improved through an outcome-blind process audit plus statistical recalibration (§9).

The core scored object is a **forecast stream**, not a one-shot number: a question owns a time series of committed probabilities (initial forecast plus trigger-driven updates), scored by time-averaged accuracy over the question's life (§7.2, §9.1). A single-forecast question is just a stream of length one, so the simple case stays simple.

Design goals, in priority order:

1. **Correctness of the loop.** Logging, resolution, and scoring must be airtight before forecast quality is optimized. A forecasting system that can't measure itself can't improve.
2. **Forecast quality.** Implement the best practices from the literature (§2) — deliberately deviating where stated in §2.4.
3. **Cheap by default.** Fully functional with zero paid tools. Paid tools (≤ $50/month) are optional plug-ins whose marginal value must be measurable within the system itself (§8).
4. **Extensible by a second developer.** A finance-focused collaborator should be able to add domain skills, data sources, and question types without touching the core loop.

Non-goals (v1): trading/bet execution with real money (paper-trading is in scope, §9.4), continuous/time-series statistical forecasting (ARIMA-style pipelines), multi-user support, a web UI.

---

## 2. Literature grounding

The design distills three bodies of work. The coding agent does not need to read these, but the *why* behind each design decision below traces back here, and future contributors should skim them.

### 2.1 Human superforecasting (Tetlock & GJP)

From *Superforecasting* (Tetlock & Gardner, 2015) and the Good Judgment Project research:

- **Outside view first.** Start from a reference class and its base rate; only then adjust with case-specific evidence (inside view). Anchoring on the base rate is the single highest-leverage habit.
- **Fermi decomposition.** Break questions into estimable sub-questions; combine explicitly.
- **Granularity matters.** Superforecasters use fine-grained probabilities (e.g. 63% not "about 60%"); rounding to the nearest 5–10% measurably worsens Brier scores.
- **Frequent small updates** beat infrequent large ones. The system should support re-forecasting on the same question and track update trajectories.
- **Actively open-minded thinking.** Seek disconfirming evidence; run pre-mortems ("it's resolution day and I was badly wrong — why?").
- **Aggregation with extremization.** The median of independent forecasts, pushed modestly toward the extremes, outperforms both individuals and naive averages.

### 2.2 LLM forecasting systems (2024–2026)

- **Halawi, Zhang, Yueh-Han & Steinhardt (2024), "Approaching Human-Level Forecasting with Language Models"** — the canonical retrieval-augmented pipeline: LM generates search queries → retrieves news → rates article relevance → summarizes → reasons → produces probability; ensembling multiple reasoning paths improves accuracy. GPT-4-era systems reached Brier ≈ 0.179 vs crowd ≈ 0.149, better on some slices.
- **AIA Forecaster (Bridgewater AIA Labs, 2025)** — first system statistically indistinguishable from superforecasters on ForecastBench (Brier 0.0753 vs superforecaster median 0.0740 on FB-Market). Three ingredients we adopt directly: (a) *agentic* search where each agent controls its own iterative search path; (b) an **ensemble of independent forecasting agents plus a supervisor agent** that reconciles disagreements by directing further targeted research; (c) **statistical post-hoc calibration** (extremization / Platt-style scaling) to correct systematic LLM biases. A further key result: on liquid prediction markets AIA *underperformed* the market (0.1258 vs 0.1106), but an **ensemble of model + market price beat both** — so when a market price exists, treat it as a strong prior/ensemble member, not something to ignore or blindly copy.
- **ForecastBench (Karger et al., 2024)** — the standard evaluation: use per-event **median** for aggregating human baselines (median beats mean under symmetric error assumptions, and empirically), report Brier with uncertainty intervals, and be paranoid about statistical power: with < ~100 resolved questions, most pairwise comparisons are noise.
- **Known failure modes documented in critiques (Bosse et al. 2024; Lopez-Lira et al. 2025):** information leakage (retrieval surfacing post-resolution documents), contamination from training data past the question's origination, small-sample overclaiming, and probabilistic incoherence (P(A) and P(¬A) not summing to 1; P(A by March) > P(A by June)). The harness must include explicit defenses (§7.4, §9.6).
- **Metaculus AI Benchmark learnings** — simple bots with good news retrieval (e.g. AskNews) rank surprisingly high; retrieval quality dominates prompt cleverness; ensembling across models helps; the platform's peer/baseline score structure is a good model for our own benchmark design.
- **Correlated-error / monoculture results (2025–2026)** — multiple prompts or "personas" on the same underlying model reading the same evidence produce *correlated* errors with cosmetic disagreement; aggregation theory (and the wisdom-of-crowds literature back to Lorenz et al. 2011) says pooling only helps to the extent errors are independent. Diversity must come from different *inputs* (evidence slices, methods, models), not different adjectives in the prompt. This directly shapes §5.7.

### 2.3 Scoring and calibration theory

- **Brier score** (mean squared error of probability vs 0/1 outcome) — primary metric; strictly proper; 0.25 = ignorance (always 0.5), lower is better.
- **Time-averaged Brier** — for forecast streams: integrate the squared error of the *active* forecast over the question's open life (equivalently, duration-weighted mean of per-forecast Brier components). Proper, and rewards updating toward truth early. This is the stream-native generalization of one-shot Brier and reduces to it for streams of length one.
- **Log score** — secondary; punishes overconfident misses harshly; useful to detect tail-risk blindness.
- **Calibration curve + Expected Calibration Error (ECE)** — bucket forecasts by stated probability, compare to observed frequency. Needs ≥ ~50 resolutions to be meaningful; report with binomial error bars.
- **Skill scores** — Brier relative to a reference (climatology/base rate, market price, naive-Claude baseline): `skill = 1 − BS_system / BS_reference`.
- **Proper decomposition** — Murphy decomposition (reliability − resolution + uncertainty) once N is large enough.
- **P&L as a scoring rule** — paper-trading divergence from a market with fractional-Kelly sizing and scoring by log-wealth is (under Kelly) equivalent to rewarding information the market lacks. It is *not* a proper scoring rule in the Brier sense and is reported as a separate track (§9.4), never blended with accuracy metrics.

### 2.4 Deliberate deviations from the benchmark literature

The tournament/benchmark literature optimizes one-shot, point-in-time forecasts because that is what benchmarks can compare. Oracle is a decision tool, not a benchmark entrant, and deviates on purpose:

1. **Streams over events.** Tetlock's own data attributes a large share of the superforecaster edge to frequent small updates, yet benchmark-shaped systems freeze a single number. Oracle's primitive is the forecast stream with trigger-driven updates (§5.14), scored by time-averaged Brier.
2. **P&L track alongside Brier.** Brier weights all questions equally; the *information* is where we disagree with the market. A paper-traded P&L-vs-market track (§9.4) is the sharper test of independent signal — you can achieve excellent Brier by cloning the crowd, but not positive P&L against it.
3. **Input diversity over persona diversity.** Per the correlated-error results above, ensemble members differ in evidence and method, not reasoning-style prompts (§5.7).
4. **Process learning over outcome learning.** At hobby volumes, individual resolutions are nearly pure noise as a teaching signal, and outcome-driven postmortems teach *resulting* (judging decisions by how the coin landed). Lessons are mined from outcome-blind process audits; outcomes feed only the statistical calibration fit (§5.12, §9.5).
5. **Loop before pipeline.** The Metaculus tournaments consistently show retrieval quality dominating prompt architecture. The build strategy (§10) therefore ships the measurement loop plus a deliberately dumb pipeline first, and lets the scoreboard justify each subsequent skill's complexity.

---

## 3. System overview

### 3.1 Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Code session (orchestrator, driven by CLAUDE.md)      │
│                                                              │
│  Skills (markdown playbooks, invoked as needed):             │
│   1. question-intake      → refine to resolvable question    │
│   2. triage               → route by type, decide effort      │
│   3. research             → agentic search, evidence log     │
│   4. base-rates           → outside view / reference classes │
│   5. modelling            → Fermi decomposition, Python      │
│   6. ensemble             → N independent forecasts + judge  │
│   7. red-team             → pre-mortem, coherence checks     │
│   8. calibrate-and-commit → final probability, log forecast  │
│   9. report               → forecast report to user          │
│  10. resolve              → resolve due forecasts, score     │
│  11. retrospect           → process audit, calibration       │
│  12. import-questions     → pull soon-closing platform Qs    │
│  13. update               → trigger-driven re-forecasts      │
│                                                              │
│  Python package `oracle/` (deterministic machinery):         │
│   ledger, scoring, calibration, aggregation, benchmarks,     │
│   resolution helpers, report rendering, CLI                  │
│                                                              │
│  State (all in-repo, git-tracked):                           │
│   data/ledger/*.json   forecasts + resolutions               │
│   data/questions/      refined question specs                │
│   data/evidence/       research logs per forecast            │
│   knowledge/lessons.md accumulated lessons                   │
│   knowledge/priors/    reusable base-rate library            │
│   reports/             rendered forecast reports             │
└─────────────────────────────────────────────────────────────┘
```

The **division of labour** is strict and is the single most important architectural decision:

- **LLM (skills) does:** question refinement, research, qualitative judgment, decomposition design, writing reasoning, choosing model structures.
- **Python (`oracle/`) does:** everything that must be deterministic and auditable — storing forecasts, computing scores, calibration math, aggregation math, benchmark bookkeeping, date logic for resolution. The LLM never computes a Brier score "in its head" and never edits the ledger directly except through the CLI.

### 3.2 The five entry workflows

1. **`forecast`** (default): user asks a question → skills 1–9 run → report + ledger entry (stream point #1).
2. **`update`**: an update trigger fires, the user asks "any updates on open questions?", or a scheduled run checks triggers → skill 13 re-runs a scoped version of the pipeline on affected open questions and commits new stream points (§5.14).
3. **`resolve`**: user (or a scheduled run) says "resolve due forecasts" → skill 10 checks each due forecast's resolution criteria against current sources, records outcomes, updates scores.
4. **`retrospect`**: after resolutions, skill 11 runs the calibration review and aggregates process-audit findings into system diffs (human approves via normal git review).
5. **`import`**: user says "import questions" (or a scheduled run) → skill 12 pulls soon-closing binary questions from Manifold/Metaculus in **blind mode** (§5.13), creates QuestionSpecs, and queues them for forecasting. This is the bootstrapping and calibration engine.

CLAUDE.md routes between these based on the user's message, and *always* starts a session by running `oracle status` (see §6.7) so the model knows about due resolutions and pending work.

### 3.3 User experience walkthroughs

What the system feels like to operate, as concrete vignettes. These are normative — if the implementation makes any of these flows clunkier than shown, that's a bug.

**Day 0 — setup (~15 minutes, once).**

```
$ git clone <repo> && cd oracle
$ uv sync
$ cp .env.example .env        # optional: add FRED key, webhook URL; all optional
$ claude
> Hi — this repo looks new. oracle status: empty ledger, no questions.
> Connectors live: manifold, metaculus, polymarket. FRED: no key (add
> FRED_API_KEY to enable macro data). Want to import a starter batch of
> questions, or ask me something?
```

No accounts are strictly required. Adding the free FRED key and a Slack webhook is a 5-minute upgrade; enabling the GitHub Actions cron (§11) is copy-paste from the README.

**The drive-by — an ad-hoc question (~10–20 min wall-clock, ~2 min of your attention).**

```
You: will the RBA cut rates at the August meeting?
Claude: Before I forecast, pinning the question down. Proposed spec:
  "Will the RBA reduce the cash rate target at its 11–12 August 2026
  meeting?" Resolves YES if the post-meeting statement announces any
  reduction; source: rba.gov.au media release; deadline 12 Aug, 18:00
  AEST. There's a near-identical Polymarket market — I'll adopt its
  resolution wording and use its price as an ensemble member. OK?
You: yes
Claude: [naive baseline logged: 0.30] [research… base rates… ensemble…
  red-team… committed F-20260704-002]
  **62%** (moderate resilience). Full report: reports/F-20260704-002.md
  Crux: market pricing implies ~58%, but the Q2 CPI print (29 Jul) is
  the swing factor — that's your first update trigger.
```

You read the report or you don't; the forecast is logged either way, and the CPI-print trigger is now in the registry, so the system will surface it when due.

**The weekly ritual (~30–45 min, the core loop).**

Open Claude Code; `oracle status` fires automatically:

```
> Since last session: 4 forecasts resolved (2 hit, 2 missed — ledger at
> 31 resolved, rolling Brier 0.19 vs naive-claude 0.24). 2 update
> triggers fired: US CPI printed hot (affects F-014), Wimbledon final
> played (F-019 resolvable). 6 fresh import candidates closing within
> 14 days. What first?
You: resolve, then updates, then show me the imports
```

You approve/trim the import batch (a one-minute skim), let it forecast the queue while you do something else, then read the new reports — which is the part you're actually here for. Every ~10 resolutions it proposes a retrospect: you review the process-audit findings and approve or reject the suggested diffs to lessons/checklist like any code review.

**The ping (with Level 1 automation on).**

Tuesday 03:00, the cron runs; Tuesday 08:00 your Slack has:

```
[oracle] 2 resolutions (F-021 ✓ Brier 0.04, F-017 ✗ Brier 0.64).
1 trigger fired: ECB decision (F-023 awaiting re-forecast).
4 imports queued. Scoreboard: reports/scoreboard.md
```

Silence means nothing needs you. When pinged, the whole obligation is: open Claude Code, say *run updates*, glance at the delta. Two minutes.

**The scoreboard conversation (whenever you or the collaborator ask).**

```
You: how are we doing? are we actually beating vanilla Claude?
Claude: 47 resolved. Mean Brier 0.178 [bootstrap CI 0.14–0.22] vs
  naive-claude 0.231 — paired Δ −0.053, CI excludes zero, win rate
  64%. So yes, the harness is earning its keep. Vs market on blind
  imports: Δ +0.011, CI straddles zero — we're not beating the crowd,
  as expected. P&L track: +2.1% log-wealth on 28 paper trades, which
  at this N is statistically indistinguishable from luck (the renderer
  says so in bold). Calibration: mild underconfidence in the 60–80%
  bucket; 3 more resolutions until the first recalibration fit.
```

**Month 2 — if the queue backs up.** You flip the schedule on in `oracle-brain.yml` (§11); the nightly run forecasts the queue and posts headlines to Slack. Your role shifts to reading reports, arguing with the collaborator about cruxes, reviewing retrospect diffs, and occasionally overriding a spec. The system runs; you supervise.

The design intent across all of these: **the human's scarce attention is spent on judgment and reading, never on bookkeeping.** Anything that feels like bookkeeping (logging, date math, score computation, resolution of platform questions, remembering what's due) is the CLI's job, and any vignette where the user is doing it manually indicates a missing CLI affordance.

---

## 4. Repository layout

```
oracle/
├── CLAUDE.md                     # orchestrator instructions (see §5.1)
├── README.md                     # human quickstart
├── pyproject.toml                # uv-managed; deps: pydantic, click, httpx,
│                                 #   numpy, scipy, matplotlib, jinja2, pytest
├── .env.example                  # optional API keys (all optional)
├── .github/workflows/
│   ├── oracle-cron.yml           # Level 1: nightly plumbing, no LLM (§11)
│   └── oracle-brain.yml          # Level 2: scheduled Claude Code, disabled (§11)
├── .claude/
│   ├── settings.json             # permissions for oracle CLI, web tools
│   └── skills/
│       ├── question-intake/SKILL.md
│       ├── triage/SKILL.md
│       ├── research/SKILL.md
│       ├── base-rates/SKILL.md
│       ├── modelling/SKILL.md
│       ├── ensemble/SKILL.md
│       ├── red-team/SKILL.md
│       ├── calibrate-and-commit/SKILL.md
│       ├── report/SKILL.md
│       ├── resolve/SKILL.md
│       ├── retrospect/SKILL.md
│       ├── import-questions/SKILL.md
│       └── update/SKILL.md
├── src/oracle/
│   ├── __init__.py
│   ├── cli.py                    # `oracle` entrypoint (click)
│   ├── models.py                 # pydantic schemas (§7)
│   ├── ledger.py                 # append-only forecast store
│   ├── scoring.py                # brier, log, ECE, skill scores, Murphy
│   ├── calibration.py            # extremization, recalibration map
│   ├── aggregation.py            # median/trimmed-mean/geo-mean-odds pools
│   ├── benchmarks.py             # baseline management & comparisons
│   ├── resolution.py             # due-date logic, resolution record helpers
│   ├── report.py                 # jinja2 rendering of reports & scoreboard
│   └── connectors/
│       ├── __init__.py           # registry + capability detection
│       ├── manifold.py           # free, no auth for reads
│       ├── metaculus.py          # free API
│       ├── polymarket.py         # free public CLOB/gamma API
│       ├── fred.py               # free with API key
│       └── asknews.py            # optional paid (guarded import)
├── data/
│   ├── ledger/                   # one JSON file per forecast (append-only)
│   ├── questions/                # refined QuestionSpec files
│   ├── sealed/                   # sealed market snapshots for blind imports (§5.13)
│   ├── evidence/                 # per-forecast research logs (markdown)
│   └── benchmarks/               # baseline forecasts (naive-claude etc.)
├── knowledge/
│   ├── lessons.md                # accumulated, numbered lessons (process-tagged)
│   ├── priors/                   # base-rate library, one md file per domain
│   ├── process-checklist.md      # outcome-blind audit checklist (§5.12)
│   └── audits/                   # one md file per forecast process audit
├── reports/                      # rendered forecast reports (md)
├── notebooks/                    # optional exploratory analysis
└── tests/                        # pytest suite for the python package
```

Everything is git-tracked, including the ledger. Git history *is* the audit trail: a forecast committed at time T provably existed at time T, which is the cheapest possible defense against "did we really predict that?" disputes and retro-fitting.

---

## 5. Orchestration and skills

### 5.1 CLAUDE.md (orchestrator)

CLAUDE.md is deliberately short (~1 page) and contains only:

1. **Identity & prime directive:** "You are Oracle, a forecasting harness. Your output is a probability with reasoning, logged before you show it to the user. A forecast that isn't logged doesn't exist."
2. **Session bootstrap:** always run `oracle status` first. If forecasts are due for resolution, tell the user and offer to run the resolve workflow before anything else. If imported questions are queued and unforecast, mention them. `oracle status` also prints whether the current session touches any blind questions, so the blind-mode restrictions (§5.13) are loaded up front.
3. **Routing table:** message looks like a question about the future → forecast workflow (skills 1–9 in order); "resolve" → skill 10; "retrospect"/"review performance" → skill 11; "import questions" → skill 12; "update"/"check open questions" → skill 13; "scoreboard" → `oracle scoreboard`.
4. **Hard rules:**
   - Never state a final probability to the user before `oracle commit` has succeeded.
   - Always produce the naive baseline (§9.2) *before* starting research.
   - Read `knowledge/lessons.md` before forecasting; cite lesson numbers when they influence the forecast.
   - Round only at the end; work in fine-grained probabilities.
   - All date math via `oracle` CLI, never mental arithmetic.
   - Never look up resolved outcomes when writing or aggregating process audits (§5.12); audits are outcome-blind by construction.
5. **Pointer to skills:** one-line description of each so the model can load them on demand.

### 5.2 Skill: question-intake

Transforms a vague user question into a **QuestionSpec** (schema §7.1). This is where most amateur forecasting fails, so the skill is strict.

Playbook:

1. **Classify the question type:** binary / multiple-choice / numeric (point-in-range) / date ("when will X"). v1 fully supports binary and numeric-via-binarization (see below); multiple-choice is decomposed into binaries that must sum to 1.
2. **Force resolvability.** Rewrite until the question passes the *stranger test*: two strangers reading only the resolution criteria on resolution day would agree on the outcome. Every spec must pin down:
   - exact metric and source of truth (e.g. "FRED series CPIAUCSL, first release, not revised"),
   - resolution timestamp and timezone,
   - edge-case handling (postponement, ambiguity, source ceases publishing → resolve VOID),
   - for numeric: the threshold(s). Numeric questions are handled as a small ladder of binary thresholds (e.g. P(CPI YoY > 2.5%), P(> 3.0%), P(> 3.5%)), which gives an implied CDF while keeping the scoring machinery binary-only in v1.
3. **Check for an existing market.** Query Manifold, Metaculus, Polymarket connectors for near-identical questions. If one exists, record its current price/community forecast in the spec (used later as ensemble member and benchmark, §9.3) and *prefer adopting the market's exact resolution criteria* — they're battle-tested and give us a free, unambiguous resolution source.
4. **Set the horizon.** Default bootstrap horizon: 7–14 days (per project plan). Warn the user if horizon > 90 days that the self-improvement loop will be slow to learn from it.
5. **Get user sign-off** on the final spec (one confirmation message), then `oracle question create`.

### 5.3 Skill: triage

Cheap classification step that sets the effort budget and route:

- **Type:** stat-model-friendly (recurring data series → modelling skill is primary) vs judgmental (one-off event → research skill is primary) vs hybrid.
- **Effort tier:** `quick` (1 research agent, no ensemble — for trivial/low-stakes), `standard` (default: full pipeline, 3-member ensemble), `deep` (5-member ensemble, supervisor round, extra red-team pass).
- **Tool plan:** which connectors are relevant (e.g. FRED for macro, market connectors for anything with a listed market).
- **Leakage risk flag:** if the question's answer may already be determined-but-unindexed (e.g. "did X happen yesterday"), flag it — that's lookup, not forecasting, and gets answered directly without polluting the ledger.

### 5.4 Skill: research

Agentic evidence-gathering, adapted from Halawi et al. and AIA:

1. **Decompose into search intents** (status quo, drivers for YES, drivers for NO, scheduled events before resolution, expert/market opinions).
2. **Iterative agentic search:** issue queries, read, refine queries based on findings — not one-shot retrieval. Prefer primary sources (official statistics, filings, transcripts) over commentary.
3. **Evidence log discipline:** every claim written to `data/evidence/<forecast_id>.md` with source URL, publication date, and a relevance/reliability grade (A–D). The final report cites only from this log.
4. **Recency and freshness:** always establish "what is the latest known state as of today" explicitly, with a dated source — the single most common LLM forecasting error is reasoning from a stale world-model.
5. **Disconfirmation pass:** at least two queries explicitly seeking evidence *against* the current leaning.
6. **Stop rule:** stop when the last two searches produced no forecast-relevant updates, or the effort-tier budget is hit.

### 5.5 Skill: base-rates

Outside view before inside view:

1. Define 1–3 candidate **reference classes** (e.g. "incumbent central bank holds rates when market-implied odds of hold > 80% one week out").
2. Source base rates: `knowledge/priors/` library first, then historical data via connectors/search, then structured estimation if no data exists (state that it's an estimate).
3. Record each base rate with N (sample size), time window, and a note on reference-class fit.
4. Output an **outside-view anchor probability** with an explicit uncertainty band. Every new, well-sourced base rate is appended to `knowledge/priors/` for reuse — this library is one of the system's compounding assets.

### 5.6 Skill: modelling

For questions with usable data (mostly the finance/macro ones your collaborator will care about):

1. Pull data via connectors into a scratch dataframe; scripts live in a per-forecast scratch dir and the *final* model script is saved alongside the evidence log for reproducibility.
2. Approved model classes for v1 (simplicity is a feature): empirical frequency counts; simple parametric fits (normal/lognormal on returns or changes); bootstrap resampling of historical windows; Monte Carlo over decomposed Fermi factors; logistic regression only if features and N justify it.
3. Every model must output a probability *and* a sensitivity note (which assumption moves the answer most).
4. Models are advisory inputs to the ensemble, not autocrats: the ensemble skill weighs model output against judgmental forecasts.

### 5.7 Skill: ensemble

Keeps AIA's ensemble + supervisor structure, but sources diversity from **inputs and methods, not personas**. Five prompt "personalities" on the same model reading the same evidence log produce correlated errors dressed up as disagreement (§2.2, correlated-error results); pooling only buys accuracy to the extent member errors are independent.

1. Spawn **k independent forecasting passes** (k from effort tier), diversified along real axes:
   - **Evidence partition:** the evidence log is split into disjoint or partially-overlapping slices (by source type or randomly); no two judgmental members read identical evidence sets. One member gets the full log as a control.
   - **Method:** at least one member is the statistical model output (when modelling ran); one member is **base-rate-only** (outside view, no news at all); one is **news-only** (no priors library, no data series).
   - **Model (optional, recommended):** one pass routed to a non-Claude model via OpenRouter (a few dollars/month of the tool budget). Cross-model decorrelation likely buys more than any prompt variation; this is also a natural first paid-tool experiment under §8.3.
   Each member returns probability + 3-line rationale + key crux. In Claude Code these run as subagent tasks.
2. **Supervisor reconciliation:** if max pairwise spread > 15 points, the supervisor identifies the crux driving disagreement — with evidence partitioning, disagreement is often *diagnostic* (it localizes which evidence slice is doing the work) — commissions one targeted research task on that crux, then re-elicits from the divergent members. One reconciliation round max (diminishing returns beyond that, per AIA).
3. **Pooling:** default pool is the **median**; also compute trimmed mean and geometric-mean-of-odds via `oracle aggregate` and record all three. If a liquid market price exists (and the question isn't blind, §5.13), include it as an ensemble member with weight equal to one agent (rationale: AIA's model+market ensemble beat both components).
4. **Resilience:** record the ensemble spread (IQR of member probabilities) and the supervisor's judgment of how much scheduled, forecast-relevant news lands before resolution. These combine into a coarse **resilience grade** (robust / moderate / fragile) committed with the forecast — a fragile 65% and a robust 65% are different objects for decision-making, and fragile forecasts get tighter update triggers (§5.14).

### 5.8 Skill: red-team

Runs after pooling, before commit:

1. **Pre-mortem:** assume the forecast resolved against you; write the three most plausible reasons why.
2. **Coherence checks:** P(A) + P(¬A) = 1 by construction; for threshold ladders, verify monotonicity (P(X > a) ≥ P(X > b) for a < b); for decomposed questions, verify the recombination arithmetic in Python, not prose.
3. **Bias checklist:** anchoring on first number seen; recency overweighting; narrative seduction (good story ≠ high probability); scope insensitivity (does the probability actually change appropriately with the horizon?).
4. **Leakage check:** confirm no evidence post-dates a "frozen" information cutoff if one applies (matters for benchmark questions, §9.6).
5. Output: either "no change" or a bounded adjustment (max ±10 points) with justification. Larger proposed moves force a loop back to research.

### 5.9 Skill: calibrate-and-commit

1. Apply the **recalibration map** if one is active (§9.5): a monotone transform fitted on ≥ 50 resolved forecasts that corrects the system's measured miscalibration (e.g. mild extremization if the system is persistently underconfident, the typical LLM failure per AIA).
2. Enforce probability floors/ceilings: nothing outside [0.01, 0.99] without written extraordinary justification (log-score protection).
3. **Outcome-blind process audit:** before commit, run the checklist in `knowledge/process-checklist.md` against this forecast's artifacts (spec unambiguous? latest-known-state established with a dated source? scheduled events before resolution checked? disconfirmation pass done? arithmetic verified in Python? evidence dates sane?). Write the pass/fail vector to `knowledge/audits/<forecast_id>.md` and embed it in the ForecastRecord. This audit — not resolution-day postmortems — is the raw material for the learning loop (§5.12).
4. **Update triggers are mandatory:** every commit must include ≥ 1 concrete, checkable trigger (a date, a data release, a market move threshold) — "if something big happens" doesn't validate. Fragile-graded forecasts (§5.7) require ≥ 3.
5. `oracle commit` — writes the ForecastRecord (§7.2): final probability, all ensemble members, pool method, calibration transform applied, resilience grade, audit vector, evidence log hash, git SHA, and the stream position (initial forecast opens a stream; updates append to it). The CLI stamps the timestamp; the LLM cannot backdate.
6. Only after a successful commit does the report get rendered.

### 5.10 Skill: report

Renders `reports/<forecast_id>.md` via `oracle report`. Fixed structure so reports are comparable over time:

1. Headline: question, **final probability**, resilience grade, horizon, resolution date.
2. TL;DR (≤ 5 sentences): the crux and where the probability comes from.
3. Outside view: reference classes and anchors.
4. Inside view: key evidence for/against, with citations from the evidence log.
5. Model output (if any) with sensitivity.
6. Ensemble table: each member's probability + one-line rationale; pooled values; market price if any.
7. Red-team notes and **update triggers** (the concrete conditions that will prompt a re-forecast, §5.14). For updates, a stream history table: prior probabilities, what changed, and the delta each trigger produced.
8. Benchmark line: naive-Claude baseline for the same question (§9.2) — shown so you can eyeball harness value on every single forecast.
9. Provenance footer: forecast ID, commit SHA, timestamp, tools used, cost estimate.

### 5.11 Skill: resolve

1. `oracle status` lists due forecasts. For each, load its QuestionSpec resolution criteria.
2. Determine outcome using the specified source of truth (fetch the FRED series, check the market's resolution, search the specific source). Imported questions are the easy case: read the platform's own resolution via the connector (and inherit VOID if the platform N/A's the market). The bar is the criteria as written — if genuinely ambiguous, resolve VOID and write a spec-defect audit entry (§5.12; spec defects are the most valuable process lessons).
3. `oracle resolve <id> --outcome yes|no|void --evidence <url/note>` — records the ResolutionRecord, computes time-averaged stream scores for the system *and all logged baselines* on that question.
4. Trigger retrospect every 10 resolutions. A single shocking miss does **not** trigger a special postmortem cycle — that is exactly the resulting reflex §5.12 is designed to suppress; it just counts toward the next scheduled review like any other resolution.

### 5.12 Skill: retrospect (the self-improvement loop)

Design principle: **learn from process, calibrate from outcomes — and mostly don't learn from misses.** At this system's volumes (tens of resolutions), an individual outcome carries almost no information about reasoning quality: a well-reasoned 70% resolves NO three times in ten, and postmortems written on those occasions systematically teach *resulting* — rules overfitted to how the coin happened to land. The learnable failures are process defects, and those are detectable without knowing the outcome. So the loop has two decoupled channels:

**Channel 1 — process (textual lessons, outcome-blind).**

1. The raw material is the audit vectors written at commit time (§5.9 step 3) against `knowledge/process-checklist.md`.
2. Retrospect aggregates audits across recent forecasts and looks for *recurring* defects: spec ambiguities, missed scheduled events, stale latest-known-state, skipped disconfirmation passes, unverified arithmetic, evidence-date problems.
3. **Distill lessons:** propose new numbered entries for `knowledge/lessons.md`. A lesson is valid only if it is (a) actionable, (b) general beyond one question, and (c) **tagged to a process defect observable at forecast time** — never to a surprising outcome. "L-014 [research]: for central-bank questions, always check the official communications calendar between now and resolution" is valid because the omission is visible in the audit regardless of how the forecast resolved. "Be more bullish on incumbents" derived from two misses is not.
4. **Extend the checklist:** genuinely new defect *types* discovered in audits are added to `process-checklist.md` itself (via reviewed diff), so the commit-time audit gets stricter over time. This is the compounding mechanism.
5. **Propose system diffs:** where a lesson implies a skill change, draft the edit to the relevant SKILL.md (or priors file, or CLAUDE.md) as a git diff for human review. The system edits itself only through reviewed commits — legible and reversible.
6. Resolution outcomes may be consulted for exactly one purpose in this channel: *prioritization* (which recurring defect co-occurs with the worst scores gets fixed first). They may not generate lessons.

**Channel 2 — outcomes (statistical, automated).**

7. Outcomes flow into the recalibration fit (§9.5) and the scoreboard segments — miscalibration, domain-level weakness, and paid-tool value are all statistical claims answered by aggregates with CIs, not by narratives about individual questions.
8. **Calibration review:** if ≥ 50 resolutions since last fit, refit the recalibration map and report whether it improved backtested Brier before activating it.

VOID resolutions are the one exception where a per-question write-up is warranted: a VOID means the *spec* was defective, which is a process defect by definition, and it goes into `knowledge/audits/` with a checklist extension proposal.

### 5.13 Skill: import-questions (blind bootstrapping)

Automatically sources forecastable questions from Manifold and Metaculus so the ledger accumulates resolutions fast — **without the pipeline ever seeing the market's opinion**. This is the primary engine for bootstrapping and for building the calibration dataset.

Playbook:

1. **Fetch candidates:** `oracle import fetch --platform manifold,metaculus --closes-within 14d --max 20` pulls open binary questions closing within the window. The connector applies quality filters *before* anything reaches the LLM:
   - binary only (v1); unambiguous, non-self-referential resolution criteria;
   - Manifold: minimum trader count (default ≥ 30) and liquidity threshold — filters out joke/personal markets ("will I finish my thesis");
   - Metaculus: minimum forecaster count (default ≥ 20);
   - excludes questions whose resolution depends on the platform itself, and (configurable) excludes categories like sports if you don't want the ledger dominated by them;
   - deduplicates against questions already in `data/questions/`.
2. **Blinding at the connector layer.** This is the critical mechanism, enforced in Python rather than by asking the LLM to look away:
   - The connector returns to the LLM only: title, description/resolution criteria, close date, category, platform question ID. Community forecast, market price, trader positions, and **comments** (which usually leak the crowd's view) are stripped before the payload ever enters context.
   - Simultaneously, the full market snapshot (price/community median, N forecasters, liquidity, timestamp) is written to `data/sealed/<question_id>.json`. The file is git-committed at import time — provably captured *before* our forecast — but no skill is permitted to read `data/sealed/` except the resolve workflow. `.claude/settings.json` deny-lists the path for read access during forecast sessions as a belt-and-braces control.
3. **Spec conversion:** the skill converts each candidate into a QuestionSpec, adopting the platform's resolution criteria verbatim and setting `origin: "import"`, `blind: true`, and the platform's own resolution as the resolution source (imported questions resolve for free — we just read the platform's resolution later).
4. **Selection & queueing:** present the filtered list to the user for a one-shot approve/trim (or `--auto-approve` for scheduled runs), then create specs and queue them. Queued imports are forecast in normal pipeline runs at `standard` tier by default.
5. **Blind-mode pipeline behavior** (enforced by a `blind` flag checked in the relevant skills):
   - question-intake: skipped (spec already exists); market-lookup step disabled.
   - research: must not fetch the source platform's page for this question, any prediction-market aggregator (Metaforecast etc.), or other markets on the same event; the red-team leakage check audits the evidence log for market-odds citations and fails the commit if found. News articles that merely mention odds in passing are flagged for judgment; direct market lookups are hard failures.
   - ensemble: the market-price ensemble member (§5.7 step 3) is disabled.
6. **Unsealing:** when the forecast is committed, `oracle commit` automatically copies the sealed snapshot's price into the benchmarks store as the `market` baseline for that question (the CLI reads `data/sealed/`; the LLM still doesn't). From that point the scoreboard can compare Oracle vs crowd on a genuinely independent basis — this is exactly the head-to-head that makes imported questions so valuable for calibration: large N, fast resolution, zero spec-writing effort, and an untainted crowd benchmark.

Why blind? Two reasons. First, calibration: if the pipeline anchors on the crowd, the resolved history measures "crowd + noise", and the recalibration map (§9.5) learns to correct the crowd's biases rather than ours. Second, benchmark integrity: Oracle-vs-market comparisons are only meaningful if Oracle's forecast is independent of the market. User-originated questions keep the default (non-blind) behavior, where a linked market is a legitimate ensemble member per AIA's model+market result — the two modes answer different questions and the ledger keeps them distinguishable via `origin` and `blind`.

### 5.14 Skill: update (forecast streams)

Frequent small updates are, per Tetlock's data, a disproportionate share of the superforecaster edge — so updating is a core workflow, not a v2 nicety. Every open question is a **stream**: an ordered series of committed probabilities, each a full ForecastRecord sharing a `stream_id`.

1. **Trigger registry:** every commit's update triggers (§5.9 step 4) are stored structured: `{type: date|release|market_move|event, check: <how to verify>, due: <when to check>}`. `oracle status` surfaces due triggers exactly like due resolutions.
2. **Trigger check:** when a trigger is due (or the user asks), a lightweight pass verifies whether it fired: fetch the release, check the date, search for the event. Cost discipline: this pass is `quick`-tier — no ensemble.
3. **Scoped re-forecast:** if the trigger fired, run a *scoped* pipeline — research restricted to what changed since the last stream point, base rates and models reused unless invalidated, ensemble at reduced k (3) seeded with the prior stream point as an explicit anchor to move *from*. The red-team question shifts to "am I over- or under-reacting to this news?" (both are documented failure modes; under-reaction is the human default, over-reaction the LLM-recency default).
4. **Commit the update** as a new stream point with a required `update_rationale`: what changed, direction and size of move, and fresh triggers. No-change updates are committed too (a re-affirmed probability after checked evidence is information, and time-averaged scoring should credit it).
5. **Blind-mode note:** updates on blind imports keep all §5.13 restrictions; the sealed snapshot is *not* refreshed (the benchmark comparison stays anchored at import time, which is conservative against us — the crowd gets no updates while we do, which is exactly the head start a stream-based system should be able to demonstrate).
6. **Scoring:** streams are scored by time-averaged Brier (§2.3, §6.2) — each probability is "active" from its commit until superseded or resolution; the score integrates squared error over the open period. Baselines are handled honestly: naive-Claude is a single point (held constant — that's the point of the comparison), while the market baseline for non-blind questions may be sampled at each update for a fair stream-vs-stream comparison.

---

## 6. Python package `oracle`

### 6.1 Principles

- Pure functions for all math; I/O isolated in `ledger.py` and `connectors/`.
- Pydantic models as the single source of schema truth; JSON on disk.
- Append-only ledger: records are never mutated; corrections are new records referencing the old (`supersedes` field).
- Everything reachable via the `oracle` CLI so the LLM interacts through a narrow, auditable interface.
- Full pytest coverage on scoring/calibration/aggregation (these must be *provably* right; property-based tests with hypothesis encouraged, e.g. Brier bounds, pool monotonicity).

### 6.2 `scoring.py`

- `brier(p, outcome) -> float`
- `stream_brier(points: list[(t, p)], resolved_at, outcome) -> float` — duration-weighted (time-averaged) Brier over the stream's active life; reduces to `brier` for a single point
- `log_score(p, outcome) -> float` (clipped at p ∈ [1e-4, 1−1e-4])
- `ece(records, bins=10) -> ECEResult` with per-bin counts and Wilson intervals
- `skill_score(bs_system, bs_reference) -> float`
- `murphy_decomposition(records) -> (reliability, resolution, uncertainty)`
- `bootstrap_ci(records, metric, n=10_000) -> (lo, hi)` — every headline comparison ships with a bootstrap CI; the scoreboard refuses to display a system-vs-baseline verdict without one (guards against the small-N overclaiming the critique literature hammers).
- `paper_trade(p_oracle, p_market, outcome, kelly_fraction=0.25) -> TradeResult` — hypothetical bet on the divergence, sized by fractional Kelly; and `log_wealth(trades) -> WealthCurve`. Quarter-Kelly default because full Kelly on a miscalibrated forecaster is a fast way to simulated ruin; the fraction is configurable and its sensitivity is reported.

### 6.3 `calibration.py`

- `extremize(p, alpha) -> float` — odds-space extremization `p' = p^α / (p^α + (1−p)^α)`
- `fit_recalibration(records) -> CalibrationMap` — fit α (and optionally a Platt-style logistic map) on resolved forecasts, selected by leave-one-out Brier; refuse to fit with N < 50
- `apply(map, p) -> float`; maps are versioned artifacts stored in `data/benchmarks/calibration/` and referenced by ID in every ForecastRecord they touch

### 6.4 `aggregation.py`

- `pool_median(ps)`, `pool_trimmed_mean(ps, trim=0.2)`, `pool_geo_mean_odds(ps)`
- `pool(ps, method, market_price=None, market_weight=1.0)`

### 6.5 `benchmarks.py`

Manages baseline forecasts per question (see §9). Key API: `record_baseline(question_id, name, p)`, `compare(system='oracle', baseline=..., segment=...)`.

### 6.6 `connectors/`

Uniform interface: `search_markets(text) -> list[MarketMatch]`, `get_price(market_id) -> PricePoint`, `get_series(series_id, ...) -> DataFrame` (FRED), and for import: `fetch_candidates(closes_within, filters) -> list[BlindCandidate]` plus `fetch_snapshot(market_id) -> SealedSnapshot`. `BlindCandidate` is a deliberately stripped type (no price, no community forecast, no comments) — blinding is enforced by the type system and connector code, not by prompt instructions. Connectors degrade gracefully: missing API key → connector reports itself unavailable, pipeline continues. A `connectors doctor` CLI subcommand prints what's live.

### 6.7 `cli.py`

```
oracle status                        # due resolutions, due triggers, queue, health
oracle question create <spec.json>
oracle commit <forecast.json>        # validates, stamps, appends to ledger/stream
oracle triggers due | check <qid>    # update-trigger registry (§5.14)
oracle stream show <qid>             # probability time series for a question
oracle baseline record <qid> <name> <p>
oracle resolve <fid> --outcome ... --evidence ...
oracle aggregate --probs 0.6,0.7,0.55 [--market 0.62]
oracle import fetch --platform manifold,metaculus --closes-within 14d --max 20
oracle import approve <candidate-ids> | --all     # create specs + seal snapshots
oracle import queue                               # list queued unforecast imports
oracle scoreboard [--segment domain|horizon|tier] [--baseline naive-claude]
oracle pnl [--kelly-fraction 0.25]   # paper-trading track vs market (§9.4)
oracle calibration fit | show | activate <id>
oracle report <fid>
oracle connectors doctor
```

---

## 7. Data schemas (pydantic, stored as JSON)

### 7.1 QuestionSpec

```python
class QuestionSpec(BaseModel):
    id: str                      # Q-YYYYMMDD-NNN
    title: str                   # short human title
    question_text: str           # full resolvable question
    q_type: Literal["binary", "threshold_ladder", "multiple_choice"]
    thresholds: list[float] | None
    resolution_criteria: str     # the stranger-test text
    resolution_source: str       # exact source of truth
    resolution_deadline: datetime  # tz-aware
    edge_cases: str
    domain: str                  # finance | macro | geopolitics | tech | sport | other
    horizon_days: int
    linked_markets: list[MarketLink]  # platform, market_id, price_at_creation
                                      # (price omitted/sealed when blind=True)
    origin: Literal["user", "import"]
    blind: bool                       # True → blind-mode restrictions (§5.13)
    sealed_snapshot: str | None       # path in data/sealed/, imports only
    created_at: datetime
    created_by: str
```

### 7.2 ForecastRecord

```python
class ForecastRecord(BaseModel):
    id: str                      # F-YYYYMMDD-NNN
    question_id: str
    stream_id: str               # shared across all points on this question
    stream_seq: int              # 0 = initial forecast, 1+ = updates
    probability: float           # final committed value
    raw_pool: dict[str, float]   # median/trimmed/geo-odds pre-calibration
    ensemble: list[EnsembleMember]  # member kind (evidence slice / method / model),
                                    #   probability, crux (one line)
    pool_method: str
    market_price_used: float | None
    calibration_map_id: str | None
    resilience: Literal["robust", "moderate", "fragile"]
    ensemble_iqr: float          # spread behind the resilience grade
    process_audit: dict[str, bool]  # checklist item -> pass, outcome-blind (§5.9)
    effort_tier: Literal["quick", "standard", "deep"]
    tools_used: list[str]
    evidence_log: str            # path
    evidence_hash: str           # sha256 of evidence file at commit
    info_cutoff: datetime | None # for anti-leakage frozen questions
    committed_at: datetime       # CLI-stamped, not LLM-supplied
    git_sha: str
    supersedes: str | None       # prior stream point (None for seq 0)
    update_rationale: str | None # required for seq >= 1
    update_triggers: list[UpdateTrigger]  # structured: type, check, due (§5.14)
```

### 7.3 ResolutionRecord

```python
class ResolutionRecord(BaseModel):
    forecast_id: str
    question_id: str
    outcome: Literal["yes", "no", "void"]
    resolved_at: datetime
    resolution_evidence: str
    scores: dict[str, float]     # brier (final point), stream_brier, log
    baseline_scores: dict[str, dict[str, float]]  # per baseline name
    pnl: TradeResult | None      # paper-trade settlement vs market, if applicable
    spec_defect_audit: str | None  # path in knowledge/audits/, VOIDs only
```

### 7.4 Anti-leakage fields

`info_cutoff` supports "frozen" evaluation questions (backtesting on already-resolved questions to test pipeline changes): when set, the research skill must restrict search by date and the red-team skill audits every evidence item's publication date against the cutoff. Backtests are stored in a separate ledger namespace (`data/ledger/backtest/`) and **never** mixed into the live scoreboard — contamination via training data means backtest numbers are upper bounds, useful for regression-testing pipeline changes, not for headline claims.

---

## 8. Tooling: free tier, paid tier, and proving marginal value

### 8.1 Free tier (default install — the system must be fully functional here)

| Capability | Tool | Notes |
|---|---|---|
| Web search & fetch | Claude Code built-in WebSearch/WebFetch | primary research channel |
| Prediction market prices | Manifold API | free, no auth for reads, generous limits |
| Community forecasts | Metaculus API | free; also candidate resolution source |
| Real-money odds | Polymarket public gamma/CLOB API | free reads |
| Macro/finance data | FRED API | free key; core for the finance use case |
| Market data | `yfinance` (best-effort) or stooq CSV | prices, vol for modelling |
| Official stats | direct fetch (ABS, BLS, Eurostat…) | via WebFetch |

### 8.2 Paid tier (≤ $50/month, each optional and independently toggleable)

Candidates, in rough order of expected value based on the Metaculus tournament experience (news retrieval quality dominates):

1. **AskNews** (~$30–50/mo tiers) — structured, dated news retrieval built for forecasting bots; the single most-cited paid edge in Metaculus AI benchmark write-ups.
2. **Exa or Tavily** search API (~$10–30/mo at hobby volume) — better semantic search + date filtering than generic web search.
3. **Financial data API** (e.g. a cheap Polygon/Twelve Data tier) — only if the finance questions outgrow yfinance.

### 8.3 Proving paid tools pay (built-in A/B)

Rule: a paid connector ships **off**, and is promoted only by evidence. Mechanism:

- When a paid connector is enabled in "trial mode", the pipeline runs research twice on eligible questions — once with, once without — producing two ensemble runs and two committed forecast variants (`variant: "paid-trial"` vs `"control"` on the ForecastRecord; only the control counts in the headline scoreboard during trial).
- After ≥ 30 resolved paired questions, `oracle scoreboard --experiment <name>` reports paired Brier difference with a bootstrap CI. Positive and CI-excluding-zero → promote (paid becomes default, control stops). Otherwise → drop and save the money.
- This doubles token cost on trial questions; triage restricts trials to `standard`-tier questions to bound spend.

---

## 9. Self-scoring, benchmarks, and self-improvement

### 9.1 The ledger is the product

Every committed forecast is immutable, timestamped by the CLI, and git-committed. The scoreboard is recomputed from the ledger on demand — no cached aggregate is authoritative.

### 9.2 Baseline: naive Claude

For every question, *before research begins*, the pipeline elicits a forecast from a clean subagent that receives only the QuestionSpec text — no tools, no evidence log, no lessons, no ensemble. This is recorded via `oracle baseline record <qid> naive-claude <p>`. It answers the central question — *does the harness beat just asking Claude?* — on a perfectly paired sample, question by question. (Ordering matters: eliciting it first prevents contamination from research summaries in context.)

Additional cheap baselines recorded automatically:
- `always-0.5` (ignorance) — computed, not elicited.
- `base-rate-only` — the outside-view anchor from the base-rates skill, before any inside view.
- `market` — market/community price at commit time when a linked market exists; for blind imports, the price from the sealed snapshot captured at import time (unsealed by the CLI at commit, §5.13). The sealed variant is the cleaner benchmark since Oracle's forecast is provably independent of it.

### 9.3 Benchmark hierarchy

Interpretation guide, in ascending difficulty to beat: always-0.5 → naive-claude → base-rate-only → market. Beating naive-claude validates the harness. Beating base-rate-only validates that research/inside view adds value over pure outside view. Beating the market is *not expected* (AIA didn't, on liquid markets) — but per AIA, check whether the *ensemble* of Oracle + market beats the market alone; that's the realistic bar for "adds information", and the one your hedge-fund friend will care about.

### 9.4 Scoreboard and the P&L track

`oracle scoreboard` renders (markdown + optional matplotlib PNGs):

- Headline: N resolved, mean stream Brier (bootstrap CI), mean log score, ECE.
- Paired comparisons vs each baseline: mean Δ Brier, CI, win rate.
- Segments: by domain, horizon bucket (≤7d / 8–30d / >30d), effort tier, question type, resilience grade (were "fragile" forecasts actually less accurate/more updated? — a self-check on the grade itself), and paid-tool experiment arm.
- Calibration curve with Wilson bars.
- Trend: rolling-20 Brier over time (is the self-improvement loop actually improving anything?).
- Honesty rule baked into the renderer: with N < 30 resolved in any cell, the cell prints `insufficient N` instead of a number.

**The P&L track** (`oracle pnl`) is the second, deliberately separate scoreboard. For every resolved question with a market baseline, it paper-trades the divergence between Oracle and the market: bet direction from the sign of (p_oracle − p_market), size by fractional Kelly (default quarter-Kelly) at the market price, settle at resolution. Reported: cumulative log-wealth curve, hit rate, average edge captured, max drawdown, and the same segment cuts as the accuracy scoreboard.

Why it earns its place: Brier weights all questions equally, but the *information content* of the system lives entirely in where it disagrees with the crowd — a forecaster can post excellent Brier by cloning the market and never add a bit of information. P&L-vs-market is only positive in expectation if the divergences are real signal. It's also the metric a trading collaborator natively thinks in, and the blind-import machinery (§5.13) makes it clean: the sealed snapshot is the provable entry price. Two disciplines: P&L is *never* blended with accuracy metrics into a composite (it isn't a proper scoring rule and has fat-tailed noise), and it inherits the same N < 30 honesty rule — expect the log-wealth curve to be dominated by noise for the first quarter, which the renderer says out loud.

### 9.5 Recalibration loop

Statistical self-improvement, separate from the textual lessons loop: fit extremization/Platt maps on resolved history (≥ 50), validate by LOO Brier, version and activate explicitly. Expected direction per the literature: LLM ensembles are underconfident after pooling and benefit from mild extremization (α ≈ 1.2–2), but we fit rather than assume. Fits use stream-initial forecasts only (updates are conditioned on the prior point and would double-count).

### 9.6 Integrity rules (learned from the critique literature)

1. Live scoreboard includes only forecasts committed before resolution-relevant information existed (enforced by timestamps; no forecasting the near-past).
2. Backtests quarantined (§7.4).
3. No deleting embarrassing forecasts — VOID exists only for genuinely defective specs, and every VOID requires a spec-defect audit entry (§5.12).
4. Small-N humility enforced in the renderer (§9.4), on both the accuracy and P&L tracks.
5. Question selection bias logged: the ledger records who originated each question (user vs imported from a platform), so "we beat naive Claude" claims can be checked for cherry-picked question mixes.
6. Blindness is enforced, then audited: connector-level stripping (§5.13) plus the red-team evidence-log audit; any blind forecast whose evidence log is found to contain market odds is flagged `blind_violated` and excluded from Oracle-vs-market comparisons and the P&L track (it still counts for Brier).
7. Updating discipline: stream updates must cite a fired trigger or new evidence; updating because the market moved (on non-blind questions) is recorded as `market_follow` and those stream points are excluded from P&L (following the market and then claiming P&L against it would be circular).

### 9.7 Bootstrapping plan (first two months) — loop first, pipeline earned

The build strategy embodies §2.4 point 5: ship the measurement loop around a deliberately dumb pipeline, then let the scoreboard justify complexity. Each pipeline stage must pay rent in measured Brier.

1. **Week 0 — the loop + Oracle-v0.** Implement ledger, scoring, resolve, scoreboard, import, and a minimal pipeline: one research pass + single forecast + commit (no ensemble, no triage, no red-team, no modelling). Smoke-test with 5 questions resolving within 7 days.
2. **Weeks 1–3 — volume on v0.** ~10 forecasts/week at 7–14 day horizons, bulk from weekly blind imports. This accumulates the resolution base *and* establishes the v0 reference curve that later stages must beat.
3. **Weeks 3–6 — add stages as experiments.** Introduce ensemble (input-diversified), then base-rates, then update streams — one at a time, each as a scoreboard experiment arm against the running configuration (same paired mechanism as paid-tool trials, §8.3). Keep what measurably helps; a stage that doesn't move Brier in ~30 paired questions gets simplified or cut. Expect, per the tournament evidence, retrieval improvements to dominate — so the first paid-tool trial (AskNews or an OpenRouter cross-model ensemble member) can start here too.
4. **Week 8ish:** first recalibration fit at 50 resolutions; first meaningful P&L read (with wide error bars, stated); collaborator starts adding finance-specific skills (earnings-event playbook, macro-release playbook) as new SKILL.md files + priors entries — no core changes required.

---

## 10. Implementation notes for the coding agent

1. **Build order (loop-first, per §9.7):** `models.py` → `ledger.py` → `scoring.py` incl. `stream_brier` and `paper_trade` (+tests) → `cli.py` (status/commit/resolve/scoreboard/pnl) → **import machinery (blind candidates, sealed snapshots, `oracle import`)** → Oracle-v0 pipeline (single research pass + commit + report) → then pipeline stages *as experiments*: ensemble (input-diversified), base-rates, update streams, triage, red-team, modelling → calibration fitting → paid-trial machinery. Everything after v0 must justify itself on the scoreboard (§9.7 step 3).
2. **Testing:** scoring/calibration/aggregation get exhaustive unit + property tests. Ledger gets append-only invariant tests. Skills are tested with a `--dry-run` flag on `oracle commit` and two golden-path fixture questions.
3. **Dependencies:** keep it boring — pydantic, click, httpx, numpy, scipy, matplotlib, jinja2, python-dateutil, pytest, hypothesis. No LangChain/agent frameworks; Claude Code *is* the agent framework.
4. **Dates:** all datetimes tz-aware UTC in storage; render in Australia/Sydney in reports.
5. **Secrets:** `.env` + `python-dotenv`; never committed; `connectors doctor` reports presence without printing values.
6. **Ergonomics:** `uv` for env management; `uv run oracle ...` should work immediately after clone.
7. **Docs:** README covers install, one worked example end-to-end (question → report → resolve → scoreboard), enabling the Actions automation (§11) including generating `CLAUDE_CODE_OAUTH_TOKEN`, and "adding a domain skill" for the collaborator.
8. **Automation-friendly CLI:** the cron workflow (§11.1) needs non-interactive variants — `oracle resolve --due --platform-only`, `oracle import fetch --auto-approve`, `--render` flags, and machine-readable exit codes (0 = nothing to do, 10 = human/LLM attention needed) so the workflow can decide whether to notify.

## 11. Deployment and automation (GitHub Actions)

The repo is on GitHub anyway (the git audit trail, §4), so GitHub Actions is the natural automation host. The design has three operating levels; the coding agent ships Levels 0 and 1 enabled and Level 2 present but disabled.

### 11.1 The level model

**Level 0 — manual.** Everything runs inside interactive Claude Code sessions. The expected rhythm is a weekly ~45-minute session (approve imports, resolve, forecast the queue, read reports) plus ad-hoc questions.

**Level 1 — cron the plumbing (default-on).** Everything deterministic runs unattended. This exploits the LLM/Python split (§3.1): import fetching, trigger checking, platform-based resolution of blind imports, scoreboard rebuilds, and notifications are pure `oracle` CLI — zero LLM cost. Workflow `.github/workflows/oracle-cron.yml`, nightly (03:00 Australia/Sydney) plus `workflow_dispatch`:

1. `oracle import fetch --closes-within 14d --auto-approve` (quality filters + seal snapshots; auto-approve is safe because filtering is deterministic, §5.13).
2. `oracle triggers due` — check dated/data-release triggers; mark fired ones.
3. `oracle resolve --due --platform-only` — resolve imports whose platform has resolved; scores recompute automatically. Bespoke questions needing judgment are queued for a human/LLM session instead.
4. `oracle scoreboard --render` and `oracle pnl --render`.
5. Commit and push any changed state (ledger, sealed, reports) with a `[oracle-cron]` message.
6. Notify (Slack incoming webhook or email via repo secret `ORACLE_WEBHOOK_URL`): fired triggers awaiting re-forecast, fresh resolutions with scores, queued imports, and any job failure. Silence means nothing needs a brain.

After Level 1, human involvement collapses to "got pinged → open Claude Code → say *run updates* → read the output."

**Level 2 — scheduled brain (shipped disabled).** Workflow `.github/workflows/oracle-brain.yml` runs Claude Code itself on a schedule via the official `anthropics/claude-code-action`, with a fixed prompt: "Run `oracle status`. Resolve anything due that needs judgment. Run the update workflow for fired triggers. Forecast queued imports (standard tier, max N per run). Commit all state." Enabled by uncommenting the `schedule:` trigger; until then it is `workflow_dispatch`-only so it can be tested by hand.

### 11.2 Authentication and cost guardrails

- **Auth for Level 2:** a Claude Pro/Max subscription token generated locally with `claude setup-token`, stored as the `CLAUDE_CODE_OAUTH_TOKEN` repo secret and passed to `claude-code-action` — runs then draw on the subscription quota rather than per-token API billing. Note Anthropic positions subscriptions as single-user; the token belongs to one maintainer and the schedule should be sized accordingly (a nightly off-hours run coexists fine with daytime interactive use).
- **Never set `ANTHROPIC_API_KEY` in this repo's workflow environment.** If both credentials are reachable, headless runs can silently bill the API account per token — a documented and expensive failure mode. CI should assert the variable is absent before invoking the action.
- **Per-run caps:** the Level 2 prompt hard-caps forecasts per run (default 5) and uses `--max-turns`-style limits so a pathological question can't consume a whole usage window.
- **Cost reality check:** a standard-tier forecast is plausibly 1–3M tokens end-to-end; at API prices that is dollars per forecast and would exceed the entire $50/month tool budget at ~10 forecasts/week. Hence the rule: LLM work rides on the subscription (interactive or OAuth-token Action); the tool budget is reserved for data/retrieval; API keys appear only as the OpenRouter cross-model ensemble member (§5.7), which is cents per forecast.

### 11.3 Concurrency and state safety

- Both workflows use a shared GitHub Actions `concurrency` group (`oracle-state`, `cancel-in-progress: false`) so cron and brain runs never interleave commits.
- Jobs `git pull --rebase` before committing; the append-only ledger makes conflicts near-impossible (new files only), and the CLI refuses to run against a dirty working tree in CI.
- Interactive sessions are advised (in CLAUDE.md) to `git pull` at session start — `oracle status` does this automatically.
- All workflow pushes are plain commits by the Actions bot; nothing force-pushes, preserving the audit trail.

### 11.4 Recommended rollout

Level 1 on day one. Hold Level 2 off for the first ~2 months deliberately: the retrospect loop needs a human approving diffs regardless, reports are the product, and the weekly judgment session is both the fun and the quality control. The trigger to enable Level 2 is observed, not planned: if the queue is chronically backed up because nobody opened Claude Code, flip the schedule on.

## 12. Open questions (decide during build, defaults given)

1. Numeric questions as full distributions (CRPS scoring) vs threshold ladders — **default: ladders in v1**, CRPS in v2.
2. Trigger-check cadence when no explicit trigger is dated — **default: none** (no dated trigger means the commit was under-specified; fix at commit time rather than polling). Time-decay triggers ("re-check at half-life of remaining horizon") are a v2 option.
3. P&L sizing: quarter-Kelly default vs fitting the fraction to realized calibration — **default: fixed quarter-Kelly in v1**; a fitted fraction is circular until the calibration map is stable.
4. Whether to enter the Metaculus AI Benchmark tournament with the same pipeline — free external validation and prize money, and the §11 automation is 90% of the required deployment. **Default: revisit after month 1.**
5. Level 2 notification depth — should the brain run post its full reports to Slack, or just headlines with links? **Default: headlines.**

---

## Appendix A: key references

- Tetlock, P. & Gardner, D. (2015). *Superforecasting: The Art and Science of Prediction.*
- Halawi, D., Zhang, F., Yueh-Han, C., & Steinhardt, J. (2024). *Approaching Human-Level Forecasting with Language Models.* arXiv:2402.18563.
- Bridgewater AIA Labs (2025). *AIA Forecaster: Technical Report.* arXiv:2511.07678.
- Karger, E. et al. (2024). *ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities.*
- Bosse, N. et al. (2024); Lopez-Lira, A. et al. (2025) — critiques of LLM forecasting evaluations (leakage, contamination, statistical power).
- Metaculus forecasting-tools & metac-bot-template repos (reference implementations for platform integration).
- Murphy, A. H. (1973). *A New Vector Partition of the Probability Score* (Brier decomposition).
