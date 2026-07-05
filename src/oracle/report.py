"""Jinja2 rendering of forecast reports, the scoreboard, and the P&L track.

This is the read-only presentation layer over the immutable ledger (§5.10,
§9.4). Three renderers:

- ``render_report`` — one markdown report per committed forecast, in the fixed
  §5.10 structure so reports stay comparable over time.
- ``render_scoreboard`` — the accuracy scoreboard (§9.4): headline stream Brier
  with a bootstrap CI, mean log score, ECE, and paired comparisons against each
  baseline, segmented on demand.
- ``render_pnl`` — the deliberately separate paper-trading track (§9.4):
  fractional-Kelly trades of Oracle's divergence from the market baseline,
  scored by log-wealth. Never blended with the accuracy metrics.

Two honesty rules are baked into the renderers, not the prompts:

- **Small-N (§9.4):** any cell backed by fewer than :data:`INSUFFICIENT_N`
  resolved questions prints ``insufficient N`` instead of a number, and the P&L
  track prints a bold noise caveat until it clears the threshold.
- **Timezone (§10.4):** storage is tz-aware UTC; every rendered timestamp is
  converted to Australia/Sydney via :func:`_fmt_sydney`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from oracle.benchmarks import compare, get_baselines
from oracle.ledger import Ledger
from oracle.models import ForecastRecord, QuestionSpec, ResolutionRecord
from oracle.scoring import bootstrap_ci, ece, log_score, log_wealth, paper_trade, stream_brier

# Small-N honesty threshold (§9.4): below this, cells print "insufficient N".
INSUFFICIENT_N = 30

# Baselines the scoreboard compares against, in display order (§9.2).
_BASELINES = ("naive-claude", "always-0.5", "base-rate-only", "market")

_SYDNEY = ZoneInfo("Australia/Sydney")

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=(), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _fmt_sydney(dt: datetime) -> str:
    """Render a UTC-stored datetime in Australia/Sydney (§10.4).

    Naive datetimes are assumed UTC (matching the ledger's storage invariant)
    before conversion. Output is ``YYYY-MM-DD HH:MM TZ`` where ``TZ`` is the
    live abbreviation (AEST/AEDT), so the DST offset is legible.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_SYDNEY)
    return local.strftime("%Y-%m-%d %H:%M %Z")


# -- forecast report ----------------------------------------------------------


def render_report(
    rec: ForecastRecord,
    spec: QuestionSpec,
    baselines: dict[str, float],
    stream: list[ForecastRecord],
    evidence_body: str = "",
) -> str:
    """Render the fixed §5.10 markdown report for a committed forecast.

    ``rec`` is the current (latest) forecast point; ``stream`` is the full
    seq-ordered history for update rendering; ``baselines`` supplies the benchmark
    lines (naive-claude, base-rate-only, market) eyeballed on every forecast (§9.2).
    ``evidence_body`` is the full text of the evidence log, embedded verbatim so the
    report is self-contained (no cross-file links).
    """
    ordered = sorted(stream, key=lambda r: r.stream_seq)
    is_update = len(ordered) > 1 or rec.supersedes is not None

    stream_rows = [
        {
            "seq": s.stream_seq,
            "probability": s.probability,
            "committed": _fmt_sydney(s.committed_at),
            "rationale": s.update_rationale or ("initial" if s.stream_seq == 0 else "—"),
        }
        for s in ordered
    ]

    trigger_due_sydney = [
        _fmt_sydney(t.due) if t.due is not None else "" for t in rec.update_triggers
    ]

    # A structured model contributed if any ensemble member is a modelling-skill
    # output (kind contains "modelling") or a distinct model (kind "model:...").
    model_members = [
        m for m in rec.ensemble
        if m.kind.startswith("model:") or "modelling" in m.kind
    ]
    has_model = bool(model_members)

    market = baselines.get("market")
    oracle_vs_market = (rec.probability - market) if market is not None else None

    template = _ENV.get_template("report.md.j2")
    return template.render(
        rec=rec,
        spec=spec,
        prob_decimal=f"{rec.probability:.2f}",
        prob_pct=f"{rec.probability * 100:.0f}%",
        deadline_sydney=_fmt_sydney(spec.resolution_deadline),
        committed_sydney=_fmt_sydney(rec.committed_at),
        trigger_due_sydney=trigger_due_sydney,
        raw_pool=rec.raw_pool,
        has_model=has_model,
        model_members=model_members,
        is_update=is_update,
        stream_rows=stream_rows,
        naive_claude=baselines.get("naive-claude"),
        base_rate_only=baselines.get("base-rate-only"),
        market=market,
        oracle_vs_market=oracle_vs_market,
        evidence_body=evidence_body.strip(),
    )


# -- resolved-question gathering ----------------------------------------------


def _resolved_streams(
    ledger: Ledger,
    segment: str | None = None,
) -> list[tuple[str, list[ForecastRecord], ResolutionRecord]]:
    """Resolved, non-void questions as ``(qid, seq-ordered stream, resolution)``.

    Segment filtering matches the latest forecast's effort tier, resilience
    grade, or experiment variant — the same cut ``benchmarks.compare`` uses so
    the headline and paired tables agree.
    """
    by_q: dict[str, list[ForecastRecord]] = {}
    for rec in ledger.all_forecasts():
        by_q.setdefault(rec.question_id, []).append(rec)

    out: list[tuple[str, list[ForecastRecord], ResolutionRecord]] = []
    for qid, recs in by_q.items():
        stream = sorted(recs, key=lambda r: r.stream_seq)
        resolution: ResolutionRecord | None = None
        for rec in stream:
            found = ledger.resolution_for(rec.id)
            if found is not None:
                resolution = found
        if resolution is None or resolution.outcome == "void":
            continue
        if segment is not None:
            latest = stream[-1]
            if segment not in (latest.effort_tier, latest.resilience, latest.variant):
                continue
        out.append((qid, stream, resolution))
    return out


# -- scoreboard ---------------------------------------------------------------


def render_scoreboard(
    ledger: Ledger,
    root: Path,
    segment: str | None = None,
) -> str:
    """Render the accuracy scoreboard (§9.4).

    Headline stream Brier / log score / ECE over resolved non-void questions
    (optionally segment-filtered), plus paired comparisons against each baseline.
    Any cell with N < :data:`INSUFFICIENT_N` prints ``insufficient N``.
    """
    resolved = _resolved_streams(ledger, segment)
    n = len(resolved)

    briers: list[float] = []
    final_pairs: list[tuple[float, int]] = []
    log_scores: list[float] = []
    for _qid, stream, resolution in resolved:
        outcome = 1 if resolution.outcome == "yes" else 0
        points = [(rec.committed_at, rec.probability) for rec in stream]
        briers.append(stream_brier(points, resolution.resolved_at, outcome))
        final_p = stream[-1].probability
        final_pairs.append((final_p, outcome))
        log_scores.append(log_score(final_p, outcome))

    sufficient = n >= INSUFFICIENT_N
    if sufficient:
        mean_brier = sum(briers) / n
        brier_ci_lo, brier_ci_hi = bootstrap_ci(briers)
        mean_log = sum(log_scores) / n
        ece_value = ece(final_pairs).ece
    else:
        mean_brier = brier_ci_lo = brier_ci_hi = mean_log = ece_value = 0.0

    comparisons = []
    for baseline in _BASELINES:
        cmp = compare(ledger, root, baseline, segment=segment)
        comparisons.append(
            {
                "baseline": baseline,
                "n": cmp.n,
                "mean_delta": cmp.mean_delta_brier,
                "ci_lo": cmp.ci_lo,
                "ci_hi": cmp.ci_hi,
                "win_rate": cmp.win_rate,
                "sufficient": cmp.n >= INSUFFICIENT_N,
            }
        )

    template = _ENV.get_template("scoreboard.md.j2")
    return template.render(
        generated_sydney=_fmt_sydney(datetime.now(timezone.utc)),
        segment=segment,
        n=n,
        sufficient=sufficient,
        threshold=INSUFFICIENT_N,
        mean_brier=mean_brier,
        brier_ci_lo=brier_ci_lo,
        brier_ci_hi=brier_ci_hi,
        mean_log=mean_log,
        ece_value=ece_value,
        comparisons=comparisons,
    )


# -- P&L track ----------------------------------------------------------------


def _max_drawdown(curve: list[float]) -> float:
    """Largest peak-to-trough drop along a cumulative log-wealth curve."""
    peak = float("-inf")
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        worst = min(worst, v - peak)
    return worst


def render_pnl(ledger: Ledger, root: Path, kelly_fraction: float = 0.25) -> str:
    """Render the paper-trading P&L track vs the market baseline (§9.4).

    For every resolved non-void question that has a ``market`` baseline, trade
    Oracle's divergence from the market with fractional Kelly, settle at
    resolution, and report the cumulative log-wealth curve, hit rate, average
    edge captured, and max drawdown. Never blended with the accuracy scoreboard.
    Prints a bold noise caveat until N clears :data:`INSUFFICIENT_N`.
    """
    resolved = _resolved_streams(ledger)
    # Trade in resolution order so the wealth curve is chronological.
    resolved.sort(key=lambda t: t[2].resolved_at)

    trades = []
    edges: list[float] = []
    bets = 0
    wins = 0
    for _qid, stream, resolution in resolved:
        baselines = get_baselines(root, _qid)
        if "market" not in baselines:
            continue
        outcome = 1 if resolution.outcome == "yes" else 0
        p_oracle = stream[-1].probability
        p_market = baselines["market"]
        tr = paper_trade(p_oracle, p_market, outcome, kelly_fraction=kelly_fraction)
        trades.append(tr)
        if tr.direction != "none":
            bets += 1
            edges.append(abs(p_oracle - p_market))
            if tr.payoff > 0:
                wins += 1

    curve = log_wealth(trades)
    n_trades = len(trades)
    final_wealth = curve[-1] if curve else 0.0
    hit_rate = (wins / bets) if bets else 0.0
    avg_edge = (sum(edges) / len(edges)) if edges else 0.0
    max_dd = _max_drawdown(curve)
    sufficient = n_trades >= INSUFFICIENT_N

    lines: list[str] = []
    lines.append("# Oracle P&L track (paper-trading vs market)")
    lines.append("")
    lines.append(f"_Generated {_fmt_sydney(datetime.now(timezone.utc))}_")
    lines.append("")
    if not sufficient:
        lines.append(
            f"**Caveat: N = {n_trades} (< {INSUFFICIENT_N}). "
            "The cumulative log-wealth curve is dominated by noise at this sample "
            "size (§9.4) — expect the first quarter to be pure luck. Do not read a "
            "trend into these numbers yet.**"
        )
        lines.append("")
    lines.append(f"- **Trades (market-baselined questions):** {n_trades}")
    lines.append(f"- **Bets placed (non-zero edge):** {bets}")
    if sufficient:
        lines.append(f"- **Cumulative log-wealth:** {final_wealth:.4f}")
        lines.append(f"- **Hit rate:** {hit_rate * 100:.0f}%")
        lines.append(f"- **Average edge captured:** {avg_edge:.4f}")
        lines.append(f"- **Max drawdown (log-wealth):** {max_dd:.4f}")
    else:
        lines.append("- **Cumulative log-wealth:** insufficient N")
        lines.append("- **Hit rate:** insufficient N")
        lines.append("- **Average edge captured:** insufficient N")
        lines.append("- **Max drawdown:** insufficient N")
    lines.append("")
    lines.append(
        "_P&L is a separate track — never blended with Brier accuracy metrics "
        "(§9.4), since it is not a proper scoring rule and has fat-tailed noise._"
    )
    lines.append("")
    return "\n".join(lines)
