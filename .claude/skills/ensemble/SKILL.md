---
name: ensemble
description: Use to run k independent forecasting passes diversified by inputs/methods, reconcile disagreement, and pool into a single probability with a resilience grade.
---

# ensemble

Run k independent forecasting passes, reconcile disagreement, and pool into one
committed probability with a resilience grade. Diversity comes from **inputs and
methods, not personas** — several prompt personalities on one model reading the
same evidence produce correlated errors dressed as disagreement (§2.2). The
committed number is **market-independent**: the prediction-market price is *never*
an ensemble member on any question (CLAUDE.md hard rule 7, §6.1).

## Playbook

1. **Spawn k independent passes** as subagent tasks (k from the effort tier,
   typically 3–5), diversified along real axes — not adjectives:
   - **base-rate-only** — outside view, no news;
   - **news-only** — current evidence, no priors library or data series;
   - **full-synthesis** — one control member reads the whole evidence log;
   - the **statistical model** output when `modelling` ran;
   - optionally **one non-Claude model** via OpenRouter (cross-model
     decorrelation buys more than any prompt tweak).
   Each returns probability + 3-line rationale + key crux.
2. **Supervisor reconciliation** — if the max pairwise spread > 15 points:
   name the crux driving disagreement (evidence partitioning makes this
   diagnostic — it localizes which slice does the work), commission **one**
   targeted research task on that crux, then re-elicit from the divergent
   members only. One reconciliation round max — this fired usefully on the IMO
   run; keep it.
3. **Pool** with `oracle aggregate --probs ...` (do **not** pass `--market`).
   Record median, trimmed mean, and geo-mean-of-odds; **default to the median**.
4. **Grade resilience** from ensemble IQR + expected pre-resolution news →
   robust / moderate / fragile. Fragile ⇒ tighter and more update triggers
   (fragile requires ≥ 3, per §5.9).
5. **Optional decision-support blend** — you *may* compute a clearly-labelled
   Oracle+market blend via `oracle aggregate --probs ... --market <p>`. This is
   the *only* place `--market` appears, and it is never the committed number.

## CLI

- `oracle aggregate --probs 0.6,0.7,0.55` — committed pool (no `--market`).
- `oracle aggregate --probs ... --market 0.62` — optional labelled blend only.
- `oracle baseline record <qid> market <p>` — record the market as a benchmark,
  not an input (non-blind questions only).

## Failure modes / notes

- **Market contamination** — including the market price as a member (done
  wrongly in early runs; it corrupted the GPT-6 and IMO forecasts) destroys the
  signal of whether the harness reconstructs the market unaided. Never do it.
- **Persona pseudo-diversity** — five voices on one model reading one evidence
  set is not an ensemble; diversify inputs/methods instead.
- **Reconciliation runaway** — one crux, one research task, one round; stop.
- **Blind questions** — do not even look up the market (CLAUDE.md blind mode);
  the red-team leakage check fails a commit that cites market odds.

See spec §5.7.
