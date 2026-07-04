# Oracle build design (v1) — build-decision delta

**Date:** 2026-07-05
**Author:** Stefano Romano (build design drafted with Claude)
**Authoritative design:** `forecasting-harness-spec.md` (Draft v1.1). This document does
**not** restate that architecture; it records only the decisions the spec leaves open and
that govern *this* implementation pass. Where this doc and the spec agree, the spec wins;
where the spec leaves a choice, this doc pins it.

---

## 1. Scope decisions (confirmed with user, 2026-07-05)

Three decisions were taken before build:

1. **Build scope: Full v1.** The complete `src/oracle/` package, all connectors, blind-import
   + sealed-snapshot machinery, calibration, P&L, reports, and GitHub Actions L0/L1 (enabled)
   + L2 (present, disabled) are all built and tested in this pass — built in the loop-first
   *order* of §10, but all delivered.
2. **Connectors: shapes + fixtures + live doctor.** Connectors are coded against the documented
   API shapes. Recorded response fixtures drive an entirely **offline** test suite. Real
   endpoints are verified on demand via `oracle connectors doctor` and a live smoke script —
   never in the pytest suite (keeps CI deterministic per §11.3).
3. **Skills: minimal stubs.** The 13 `SKILL.md` playbooks are delivered as stubs: identity,
   one-paragraph purpose, the numbered steps from their §5 subsection compressed to bullets,
   and a pointer to the spec section. They are **not** fully elaborated playbooks in this pass.
   `CLAUDE.md` is the exception — it is built in full, since it is the router / prime directive,
   not a playbook.

### Definition of done for this pass

- `uv run pytest` passes offline with property tests (hypothesis) on all pure-math modules,
  append-only invariant tests on the ledger, fixture-replay tests on connectors, and a
  `--dry-run` golden-path test over two fixture questions.
- `uv run oracle status` / `scoreboard` / `pnl` / `connectors doctor` / `import ...` / `commit`
  / `resolve` all run end-to-end against on-disk state.
- Repo is a git repo; all state dirs exist and are tracked; README documents one worked
  example end-to-end (question → report → resolve → scoreboard) and how to enable automation.

### Explicitly out of scope

- Live, months-long forecasting operation.
- Anything §12 defers to v2: CRPS/full-distribution numeric scoring, time-decay triggers,
  calibration-fitted Kelly fraction.
- Fully-elaborated skill playbooks (deferred; stubs only).

---

## 2. Build order (loop-first, per §9.7 / §10)

Each phase is verified (its tests green) before the next begins.

1. **Substrate.** `models.py` (all §7 pydantic schemas) → `ledger.py` (append-only, one JSON
   file per forecast, `supersedes` for corrections) → `scoring.py` (`brier`, `stream_brier`,
   `log_score`, `ece`, `skill_score`, `murphy_decomposition`, `bootstrap_ci`, `paper_trade`,
   `log_wealth`) with full unit + property tests.
2. **Deterministic services.** `aggregation.py` (median / trimmed-mean / geo-mean-odds / `pool`),
   `calibration.py` (`extremize`, `fit_recalibration` with N≥50 refusal, `apply`, versioned maps),
   `benchmarks.py` (`record_baseline`, `compare`), `resolution.py` (due-date logic, resolution
   record helpers), `report.py` (jinja2 report + scoreboard rendering, N<30 honesty rule).
3. **CLI.** `cli.py` (click) wiring every §6.7 subcommand; non-interactive variants
   (`--auto-approve`, `--due --platform-only`, `--render`); machine-readable exit codes
   (0 = nothing to do, 10 = attention needed) per §10.8.
4. **Connectors.** `connectors/__init__.py` registry + capability detection; `manifold`,
   `metaculus`, `polymarket`, `fred`, `asknews` (guarded optional import); `BlindCandidate`
   (stripped type — no price/community/comments) and `SealedSnapshot`; recorded fixtures;
   `doctor` subcommand + live smoke script.
5. **Import machinery.** Blind fetch → quality filters (trader/forecaster minimums, dedupe,
   category excludes) → seal snapshot to `data/sealed/` (git-committed at import) → queue →
   unseal-at-commit copies sealed price into the `market` baseline (CLI reads sealed; skills
   never do; `.claude/settings.json` deny-lists the path).
6. **Oracle-v0 pipeline glue.** `CLAUDE.md` (full), 13 `SKILL.md` stubs, `.claude/settings.json`,
   two golden fixture questions, `oracle commit --dry-run` path.
7. **Automation & docs.** `.github/workflows/oracle-cron.yml` (L1, enabled),
   `oracle-brain.yml` (L2, `workflow_dispatch`-only / schedule commented out), README,
   `.env.example`. CI asserts `ANTHROPIC_API_KEY` is absent (§11.2).

---

## 3. Test strategy

| Module | Tests |
|---|---|
| `scoring` | Unit + hypothesis: Brier ∈ [0,1], 0 at perfect / 1 at certain-wrong; `stream_brier` reduces to `brier` at length 1; duration weights sum correctly; log-score clipping; bootstrap CI ordering (lo ≤ hi). |
| `calibration` | `extremize` identity at α=1, monotone, order-preserving; `fit_recalibration` refuses N<50; map round-trips within tolerance. |
| `aggregation` | Pool monotonicity, bounds, geo-mean-odds vs median relationships; market-weight behaviour. |
| `ledger` | Append-only invariant (no in-place mutation), corrections create new records referencing `supersedes`, timestamps CLI-stamped not caller-supplied. |
| `connectors` | Fixture-replay parsing; `BlindCandidate` provably carries no price/community/comment fields; graceful-degrade when key absent. |
| `cli` | `--dry-run` golden path over 2 fixture questions; exit codes 0 vs 10. |

No network in the suite. Live verification is `oracle connectors doctor` + `scripts/smoke_connectors.py`, run manually.

---

## 4. Scaffolding decisions

- `git init` on the repo (done) — git history is the audit trail (§4).
- `uv` pins **Python 3.12** (spec target runtime; system Python is 3.14).
- Dependencies exactly the §10.3 set: pydantic, click, httpx, numpy, scipy, matplotlib,
  jinja2, python-dateutil, pytest, hypothesis. No LangChain / agent frameworks.
- All datetimes tz-aware UTC in storage; rendered Australia/Sydney in reports (§10.4).
- Secrets via `.env` + python-dotenv, never committed; `doctor` reports presence, not values.
- State dirs (`data/ledger`, `data/questions`, `data/sealed`, `data/evidence`,
  `data/benchmarks`, `knowledge/priors`, `knowledge/audits`, `reports`, `notebooks`) created
  with `.gitkeep`.

---

## 5. Execution

Implementation plan authored via the writing-plans skill, then executed via `/ultracode`
multi-agent orchestration (user-requested). The loop-first build order above defines the
plan's phase boundaries.
