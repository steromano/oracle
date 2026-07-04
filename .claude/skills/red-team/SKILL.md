---
name: red-team
description: Use after pooling and before commit to pre-mortem, check coherence and biases, and audit for information leakage.
---

# red-team

Adversarial pass that runs after pooling, before commit. Output is either "no
change" or a bounded adjustment (max ±10 points) with justification; larger
proposed moves force a loop back to `research`.

- **Pre-mortem:** assume the forecast resolved against you; write the three most
  plausible reasons why.
- **Coherence checks:** P(A) + P(¬A) = 1; threshold ladders monotone
  (P(X>a) ≥ P(X>b) for a<b); verify decomposition arithmetic in Python (via the
  CLI), not prose.
- **Bias checklist:** anchoring on the first number; recency overweighting;
  narrative seduction (good story ≠ high probability); scope insensitivity (does
  the probability move appropriately with the horizon?).
- **Leakage check:** no evidence post-dates a frozen `info_cutoff` if one
  applies. **Blind imports:** any market-odds citation in the evidence log is a
  hard commit failure (sets `blind_violated`).

See spec §5.8.
