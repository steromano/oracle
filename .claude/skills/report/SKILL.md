---
name: report
description: Use after a successful commit to render the fixed-structure forecast report for the user.
---

# report

Renders `reports/<forecast_id>.md` via `oracle report <fid>`. The report is
**generated from the committed ledger record**, not written by hand — so this
skill's real job is (a) confirm the committed ForecastRecord already carries the
fields the report needs (ensemble table, resilience grade, update triggers,
benchmarks) and (b) invoke the renderer. The structure is fixed so reports are
comparable across every forecast and over time.

## Playbook

1. **Precondition:** `oracle commit` has succeeded for this `<fid>`. If not,
   stop — there is nothing to render (report never invents a probability).
2. **Verify the record populates the report.** The renderer only surfaces what
   was committed, so confirm the ForecastRecord carried: the **ensemble table**
   (members + pooled), the **resilience grade**, the **update triggers**, and
   the **benchmarks** (naive-claude always; market when one exists). A gap here
   means fix it upstream (re-commit), not patch the report.
3. **Run** `oracle report <fid>` to render `reports/<forecast_id>.md`.
4. **Check the benchmark line reflects market-independence.** The committed
   probability is Oracle's own and market-independent. The benchmark line lists,
   as *yardsticks only*: **naive-claude**, **base-rate-only**, and **the market
   price** when one was recorded — never as inputs. It may also show an optional,
   clearly-labelled **"Oracle vs market" gap** (how far the independent forecast
   sits from the market). Confirm the market is presented as a benchmark, not a
   forecast component.
5. **Hand the rendered report to the user.** Fixed section order (§5.10):
   Headline · TL;DR · Outside view · Inside view · Model output · Ensemble table
   · Red-team + update triggers (stream-history table for updates) · Benchmark
   line · Provenance footer.

## CLI

`oracle report <fid>` (renders from the ledger). Upstream, the record came from
`oracle commit`; benchmarks from `oracle baseline record <qid> <name> <p>`.

## Failure modes / notes

- **Report is a renderer, never an author.** If a section is empty, the fix is
  in the committed record, not the markdown.
- **Never fold the market into the committed number.** It appears only in the
  benchmark line and the optional gap. Blind questions never show a market at
  all (no price was ever looked up).
- Keep fine-grained probabilities as committed; do not re-round in the report.

See spec §5.10.
