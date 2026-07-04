---
name: question-intake
description: Use first in the forecast workflow to turn a vague user question into a strict, resolvable QuestionSpec before any forecasting begins.
---

# question-intake

Transforms a vague user question into a **QuestionSpec** (schema §7.1). This is
where most amateur forecasting fails, so be strict: the goal is a question two
strangers reading only the resolution criteria on resolution day would resolve
identically.

- **Classify the type:** binary / multiple-choice / numeric / date. v1 supports
  binary and numeric-via-binarization; decompose multiple-choice into binaries
  that sum to 1; handle numeric as a small ladder of binary thresholds.
- **Force resolvability (stranger test):** pin exact metric + source of truth,
  resolution timestamp + timezone, edge-case handling (postponement, ambiguity,
  source stops publishing → VOID), and threshold(s) for numeric.
- **Check for an existing market** via the connectors; if one exists, prefer
  adopting its battle-tested resolution wording and record its price in the spec
  (later an ensemble member + benchmark). **Skip this step for blind imports.**
- **Set the horizon:** default 7–14 days; warn if > 90 days (slow to learn).
- **Get user sign-off**, then run `oracle question create <spec.json>`.

See spec §5.2 (and §7.1 for the schema).
