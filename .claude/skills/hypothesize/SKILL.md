---
name: hypothesize
description: Use after triage and before research to brainstorm the causal drivers and mechanisms that could move the outcome, so research is directed by hypotheses rather than defaulting to historical trends.
---

# hypothesize

Before researching, generate an explicit **causal map** of what could actually
move this question — conventional *and* structural/non-obvious. This is Oracle's
antidote to anchoring on base rates and historical trends: left unprompted, the
harness will study the past and miss regime changes. (On the AU-unemployment run
it only surfaced AI-diffusion because the user raised it — this step makes the
harness do that itself.) The output becomes the research agenda and seeds the
ensemble's evidence/method partitions.

## Playbook

1. **Frame the outcome mechanistically.** State what would have to be true for the
   question to resolve YES, and separately for NO — in terms of drivers, not vibes.
2. **Brainstorm 5–8 candidate drivers/mechanisms**, deliberately spanning:
   - the **conventional** (the obvious cyclical/direct causes), and
   - the **structural / non-obvious** (regime shifts, second-order effects, new
     technology, policy/behaviour change) — force at least two of these.
   Think like a superforecaster running a pre-mortem *forwards*: "what could make
   the consensus wrong?"
3. **Tag each hypothesis** with: direction (pushes YES or NO), rough plausibility
   (high/med/low), and **what evidence would confirm or deny it** (this is the
   research query it generates).
4. **Prioritise.** Mark the 2–4 hypotheses most likely to be *decision-relevant*
   (high plausibility × high impact) — research spends its budget there first.
5. **Hand off:** write the hypothesis list into the evidence log header
   (`data/evidence/<fid>.md`) as the research agenda, and use it to define the
   research skill's search intents and the ensemble's evidence slices (e.g. a
   "structural-driver" member vs a "base-rate" member).

## Failure modes / notes

- **Trend-only tunnel vision** — if every hypothesis is "extrapolate the past,"
  you have not done this step. Force the structural/non-obvious ones.
- **Symmetry** — include drivers that push *both* directions; a one-sided list is
  motivated reasoning.
- **Not a forecast** — this step produces hypotheses to test, not probabilities.
  No `oracle` writes happen here; it feeds `research` and `ensemble`.
- Keep it quick (a `quick`-tier question may do a 3-line version); depth scales
  with the effort tier set in `triage`.

See spec §2.1 (Fermi decomposition, actively open-minded thinking); this skill
operationalises them as an explicit pre-research phase.
