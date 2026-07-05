---
name: red-team
description: Use after pooling and before commit to pre-mortem, check coherence and biases, and audit for information leakage.
---

# red-team

Adversarial pass that runs after pooling and before `calibrate-and-commit`. It
tries to break the pooled number, not defend it. Output is one of exactly two
things: **"no change"**, or a **bounded adjustment (max ±10 points)** with a
one-line justification. A proposed move larger than 10 points is not applied
here — it means the pool is unstable, so loop back to `research` (and re-pool)
rather than nudging.

## Playbook

1. **Pre-mortem.** Assume the forecast resolved against you. Write the three
   most plausible "it resolved against me — why?" stories. If any is both
   plausible and under-weighted in the evidence, that is your adjustment
   candidate.
2. **Coherence checks — in Python, not prose.** P(A) + P(¬A) = 1 by
   construction. For threshold ladders, verify **monotonicity**: P(X > a) ≥
   P(X > b) for every a < b. For decomposed questions, verify the recombination
   arithmetic. Compute these with the CLI (`oracle aggregate --probs …`) or a
   scratch calc — never eyeball a ladder as "looks monotone".
3. **Bias checklist.** Anchoring on the first number seen; recency
   overweighting; narrative seduction (a good story ≠ high probability); scope
   insensitivity (does the probability actually move with the horizon?).
4. **Over/under-reaction check (updates).** For a re-forecast, pull the prior
   stream point (`oracle stream show <qid>`) and ask whether the delta matches
   the news: a large move on thin news is overreaction; an unchanged number
   after materially new evidence is underreaction/prior-anchoring. Both are
   defects.
5. **Leakage check.** Confirm no evidence post-dates a frozen `info_cutoff` if
   one applies (benchmark questions, §9.6). **Blind imports:** any
   market-odds citation in the evidence log is a hard commit failure (sets
   `blind_violated`) — a recorded market *benchmark* is fine, a market price
   used as *evidence* is not.
6. **Emit the verdict.** "No change", or a ±≤10-point adjustment with
   justification. Larger → back to `research`.

## CLI

`oracle aggregate --probs 0.6,0.7,0.55` (verify monotonicity / recombination
arithmetic) · `oracle stream show <qid>` (prior points, for the
over/under-reaction check).

## Failure modes / notes

- Do not use red-team to import the market price — it is a benchmark, never an
  ensemble member or an "adjustment target".
- A ±10-point nudge is a ceiling, not a target; most passes should end "no
  change".
- Checking monotonicity or arithmetic in your head is itself a process defect —
  it gets logged in the commit-time audit.
- Never look up a resolved outcome here; the pass is outcome-blind.

See spec §5.8.
