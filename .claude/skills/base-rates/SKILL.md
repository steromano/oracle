---
name: base-rates
description: Use to establish the outside-view anchor (reference classes + base rates) before any inside-view adjustment.
---

# base-rates

Outside view **first**. This is a distinct step that produces an explicit
anchor probability — reference-class forecasting in the Kahneman/Tetlock sense —
*before* any inside-view reasoning, ensemble pass, or model runs. Anchoring on
the base rate is the highest-leverage superforecasting habit, and it only works
if the anchor exists on its own before the inside view can contaminate it. Do
not let the outside view get folded into an ensemble member; commit it as a
standalone `base-rate-only` baseline.

## Playbook

1. **Define 1–3 reference classes.** State each precisely enough to count
   against (e.g. "US recessions within 12 months of a first Fed cut, 1960–2024";
   "incumbent central bank holds when market-implied odds of hold > 80% one week
   out"). Prefer a couple of angles over one forced class.
2. **Source each base rate**, in order: the `knowledge/priors/` library first,
   then historical data via connectors/search, then structured estimation if no
   data exists (say plainly it is an estimate). For each, record **N (sample
   size) + time window + a reference-class-fit note** (how well this class maps
   to the actual question, and what's different this time).
3. **Output the outside-view anchor** — a single probability **with an explicit
   uncertainty band** (e.g. 0.30, band 0.20–0.45) — reconciling the classes if
   you defined more than one. Do this **before** any inside-view adjustment.
4. **Record it** as the baseline: `oracle baseline record <qid> base-rate-only <p>`.
5. **Append** every genuinely new, well-sourced base rate to `knowledge/priors/`
   so it is reusable — this library is a compounding asset.

## CLI

- `oracle baseline record <qid> base-rate-only <p>` — log the outside-view anchor.

## Failure modes / notes

- **Anchor folded into the ensemble** — the retrospective failure. Base-rates is
  its own step that emits an explicit anchor first; the ensemble reads that
  anchor, it does not replace it.
- **Reference class too narrow** (N ≈ 1 → not a base rate, it's an anecdote) or
  **too broad** (poor fit) — the fit note should flag which risk applies.
- **Point estimate with no band** — an anchor without an uncertainty range gives
  downstream steps false precision. Always attach the band.
- **Never treat a market price as a base rate** — a market is a benchmark
  (§ hard rule 7), not a reference class.
- **Silent priors** — a new base rate not appended to `knowledge/priors/` is
  work thrown away.

See spec §5.5.
