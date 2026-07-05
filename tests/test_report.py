"""Tests for the report / scoreboard / pnl renderers (Task 8, §5.10 / §9.4).

The renderers turn immutable ledger records into human-readable markdown. Three
invariants are load-bearing and tested here:

- The forecast report has a fixed §5.10 structure: headline probability,
  resilience grade, ensemble table, update triggers, and the naive-claude
  benchmark line all appear.
- Small-N honesty (§9.4): any scoreboard cell with N < 30 prints ``insufficient
  N`` rather than a number; at N >= 30 the headline ships a bootstrap CI.
- The P&L track prints a bold noise caveat while N is small and dates render in
  Australia/Sydney everywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle.benchmarks import record_baseline
from oracle.ledger import Ledger
from oracle.models import (
    EnsembleMember,
    ForecastRecord,
    QuestionSpec,
    ResolutionRecord,
    UpdateTrigger,
)
from oracle.report import (
    INSUFFICIENT_N,
    _fmt_sydney,
    render_pnl,
    render_report,
    render_scoreboard,
)

UTC = timezone.utc


# -- builders -----------------------------------------------------------------


def _forecast(
    *,
    fid: str,
    question_id: str,
    stream_seq: int = 0,
    probability: float = 0.63,
    committed_at: datetime,
    resilience: str = "moderate",
    effort_tier: str = "standard",
    market_price_used: float | None = None,
    supersedes: str | None = None,
    update_rationale: str | None = None,
) -> ForecastRecord:
    return ForecastRecord(
        id=fid,
        question_id=question_id,
        stream_id=f"S-{question_id[2:]}",
        stream_seq=stream_seq,
        probability=probability,
        raw_pool={"median": probability},
        ensemble=[
            EnsembleMember(
                kind="method:base-rate",
                probability=0.55,
                crux="historical frequency of comparable events",
            ),
            EnsembleMember(
                kind="evidence-slice:A",
                probability=0.70,
                crux="recent leading indicator turned positive",
            ),
        ],
        pool_method="median",
        market_price_used=market_price_used,
        calibration_map_id=None,
        resilience=resilience,
        ensemble_iqr=0.08,
        process_audit={"coherence": True, "arithmetic-verified": True},
        effort_tier=effort_tier,
        tools_used=["manifold", "fred"],
        evidence_log="data/evidence/x.md",
        evidence_hash="a" * 64,
        info_cutoff=None,
        committed_at=committed_at,
        git_sha="deadbeefcafe",
        supersedes=supersedes,
        update_rationale=update_rationale,
        update_triggers=[
            UpdateTrigger(
                type="release",
                check="next CPI print exceeds 3.5%",
                due=datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ],
    )


def _spec(question_id: str) -> QuestionSpec:
    return QuestionSpec(
        id=question_id,
        title="Will inflation exceed target by year end?",
        question_text="Will headline CPI exceed 3% YoY at the December print?",
        q_type="binary",
        thresholds=None,
        resolution_criteria="Resolves YES if the December CPI YoY print is > 3.0%.",
        resolution_source="Official statistics agency release",
        resolution_deadline=datetime(2026, 7, 5, 2, 0, tzinfo=UTC),
        edge_cases="Revisions after the initial print do not change resolution.",
        domain="macro",
        horizon_days=180,
        linked_markets=[],
        origin="user",
        blind=False,
        sealed_snapshot=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by="stefano",
    )


def _resolution(
    fid: str,
    question_id: str,
    outcome: str,
    resolved_at: datetime,
) -> ResolutionRecord:
    return ResolutionRecord(
        forecast_id=fid,
        question_id=question_id,
        outcome=outcome,
        resolved_at=resolved_at,
        resolution_evidence="official source",
        scores={},
        baseline_scores={},
        pnl=None,
        spec_defect_audit=None,
    )


def _populate(state_root: Path, n: int, *, with_market: bool = False) -> Ledger:
    """Create ``n`` single-point resolved questions, alternating outcomes."""
    led = Ledger(state_root)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = datetime(2026, 2, 1, tzinfo=UTC)
    for i in range(n):
        qid = f"Q-20260101-{i + 1:03d}"
        fid = f"F-20260101-{i + 1:03d}"
        outcome = "yes" if i % 2 == 0 else "no"
        prob = 0.6 if i % 2 == 0 else 0.4
        market = 0.5 if with_market else None
        led.append_forecast(
            _forecast(
                fid=fid,
                question_id=qid,
                probability=prob,
                committed_at=t0,
                market_price_used=market,
            )
        )
        led.append_resolution(_resolution(fid, qid, outcome, r))
        record_baseline(state_root, qid, "naive-claude", 0.5)
        if with_market:
            record_baseline(state_root, qid, "market", 0.5)
    return led


# -- _fmt_sydney --------------------------------------------------------------


def test_fmt_sydney_converts_utc_to_aest():
    # 02:00 UTC on 2026-07-05 is 12:00 AEST (UTC+10, no DST in July).
    s = _fmt_sydney(datetime(2026, 7, 5, 2, 0, tzinfo=UTC))
    assert "2026-07-05" in s
    assert "12:00" in s


def test_fmt_sydney_handles_dst_summer():
    # 22:00 UTC on 2026-01-01 is 09:00 AEDT next day (UTC+11 in January).
    s = _fmt_sydney(datetime(2026, 1, 1, 22, 0, tzinfo=UTC))
    assert "2026-01-02" in s
    assert "09:00" in s


# -- render_report ------------------------------------------------------------


def test_report_contains_fixed_structure(state_root: Path):
    spec = _spec("Q-20260101-001")
    rec = _forecast(
        fid="F-20260101-001",
        question_id="Q-20260101-001",
        probability=0.63,
        committed_at=datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
    )
    baselines = {"naive-claude": 0.5, "always-0.5": 0.5}
    out = render_report(rec, spec, baselines, stream=[rec])

    # Headline: final probability (fine-grained) + resilience grade.
    assert "63" in out  # 0.63 / 63%
    assert "moderate" in out
    # Ensemble table: member kinds and their cruxes appear.
    assert "method:base-rate" in out
    assert "evidence-slice:A" in out
    assert "historical frequency of comparable events" in out
    # Update triggers (§5.14).
    assert "next CPI print exceeds 3.5%" in out
    # Benchmark line: LLM (web-enabled) baseline (§9.2).
    assert "LLM" in out
    # Provenance footer.
    assert "F-20260101-001" in out
    assert "deadbeefcafe" in out


def test_report_is_self_contained_and_embeds_evidence(state_root: Path):
    spec = _spec("Q-20260101-001")
    rec = _forecast(
        fid="F-20260101-001",
        question_id="Q-20260101-001",
        probability=0.63,
        committed_at=datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
    )
    evidence = "## Latest known state\n- [A] 2026-01-01 dated fact from primary source."
    baselines = {"naive-claude": 0.5, "base-rate-only": 0.4, "market": 0.55}
    out = render_report(rec, spec, baselines, stream=[rec], evidence_body=evidence)

    # Evidence is embedded verbatim — the report is self-contained (no file link).
    assert "dated fact from primary source" in out
    assert "data/evidence/x.md" not in out  # no cross-file link to the evidence log
    # All three benchmarks + the Oracle-minus-market gap (0.63 - 0.55 = +0.08).
    assert "base-rate-only" in out and "market" in out
    assert "+0.08" in out


def test_report_renders_dates_in_sydney(state_root: Path):
    spec = _spec("Q-20260101-001")
    rec = _forecast(
        fid="F-20260101-001",
        question_id="Q-20260101-001",
        committed_at=datetime(2026, 7, 5, 2, 0, tzinfo=UTC),
    )
    out = render_report(rec, spec, {"naive-claude": 0.5}, stream=[rec])
    # resolution deadline 02:00 UTC 2026-07-05 -> 12:00 Sydney.
    assert "2026-07-05" in out
    assert "12:00" in out


def test_report_shows_stream_history_for_updates(state_root: Path):
    spec = _spec("Q-20260101-001")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 5, tzinfo=UTC)
    first = _forecast(
        fid="F-20260101-001",
        question_id="Q-20260101-001",
        stream_seq=0,
        probability=0.55,
        committed_at=t0,
    )
    second = _forecast(
        fid="F-20260101-002",
        question_id="Q-20260101-001",
        stream_seq=1,
        probability=0.72,
        committed_at=t1,
        supersedes="F-20260101-001",
        update_rationale="leading indicator flipped positive",
    )
    out = render_report(second, spec, {"naive-claude": 0.5}, stream=[first, second])
    # Stream history table shows the prior probability and the update rationale.
    assert "0.55" in out
    assert "leading indicator flipped positive" in out


# -- render_scoreboard --------------------------------------------------------


def test_scoreboard_insufficient_n_below_threshold(state_root: Path):
    led = _populate(state_root, 5)
    out = render_scoreboard(led, state_root)
    assert "insufficient N" in out
    # N itself is still reported honestly.
    assert "5" in out


def test_scoreboard_shows_bootstrap_ci_at_high_n(state_root: Path):
    led = _populate(state_root, INSUFFICIENT_N + 5)  # 35 resolved
    out = render_scoreboard(led, state_root)
    # Headline mean Brier is now a real number with a bootstrap CI, not a fig leaf.
    assert "insufficient N" not in out.split("## Paired")[0]
    assert "CI" in out


def test_scoreboard_segment_filter(state_root: Path):
    led = _populate(state_root, 4)
    out = render_scoreboard(led, state_root, segment="standard")
    assert "standard" in out


# -- render_pnl ---------------------------------------------------------------


def test_pnl_noise_caveat_bold_at_low_n(state_root: Path):
    led = _populate(state_root, 5, with_market=True)
    out = render_pnl(led, state_root)
    # The noise warning must be present and bold (markdown **...**) at low N.
    assert "**" in out
    lowered = out.lower()
    assert "noise" in lowered


def test_pnl_reports_metrics_when_market_present(state_root: Path):
    led = _populate(state_root, 5, with_market=True)
    out = render_pnl(led, state_root)
    lowered = out.lower()
    assert "log-wealth" in lowered or "log wealth" in lowered
    assert "hit rate" in lowered
    assert "drawdown" in lowered


def test_pnl_handles_no_market_baselines(state_root: Path):
    led = _populate(state_root, 3, with_market=False)
    out = render_pnl(led, state_root)
    # No market baselines -> nothing to trade, but the renderer must not crash.
    assert isinstance(out, str)
    assert len(out) > 0


def test_report_shows_structured_model_when_present(state_root: Path):
    from oracle.models import ForecastRecord, EnsembleMember, UpdateTrigger
    spec = _spec("Q-20260101-001")
    rec = ForecastRecord(
        id="F-20260101-050", question_id="Q-20260101-001", stream_id="S-1", stream_seq=0,
        probability=0.48, raw_pool={"median": 0.48},
        ensemble=[
            EnsembleMember(kind="method:modelling-barrier-touch", probability=0.48,
                           crux="GBM barrier-touch to the ATH"),
            EnsembleMember(kind="method:base-rate-outside", probability=0.50, crux="outside view"),
        ],
        pool_method="median", resilience="moderate", ensemble_iqr=0.02, process_audit={},
        effort_tier="standard", tools_used=["python-model"], evidence_log="", evidence_hash="a" * 64,
        committed_at=datetime(2026, 1, 2, tzinfo=UTC), git_sha="x",
        update_triggers=[UpdateTrigger(type="date", check="c", due=None)],
    )
    out = render_report(rec, spec, {"naive-claude": 0.5}, stream=[rec])
    assert "structured model" in out
    assert "modelling-barrier-touch" in out  # the model member is shown
    assert "No structured model" not in out
