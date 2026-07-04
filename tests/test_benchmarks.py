"""Tests for the baseline store and paired comparison (Task 6, §6.5 / §9.2-9.4).

Baselines are per-question single-point forecasts (naive-claude, always-0.5,
base-rate-only, market). ``compare`` pairs the system's time-averaged stream
Brier against a baseline's constant-point Brier, question by question, and ships
a bootstrap CI plus win rate so callers can enforce the N<30 honesty rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle.benchmarks import Comparison, compare, get_baselines, record_baseline
from oracle.ledger import Ledger
from oracle.models import EnsembleMember, ForecastRecord, ResolutionRecord, UpdateTrigger

UTC = timezone.utc


# -- fixtures / builders ------------------------------------------------------


def _forecast(
    *,
    fid: str,
    question_id: str,
    stream_seq: int = 0,
    probability: float = 0.7,
    committed_at: datetime,
) -> ForecastRecord:
    return ForecastRecord(
        id=fid,
        question_id=question_id,
        stream_id=f"S-{question_id[2:]}",
        stream_seq=stream_seq,
        probability=probability,
        raw_pool={"median": probability},
        ensemble=[
            EnsembleMember(kind="method:base-rate", probability=probability, crux="x"),
        ],
        pool_method="median",
        market_price_used=None,
        calibration_map_id=None,
        resilience="moderate",
        ensemble_iqr=0.05,
        process_audit={"coherence": True},
        effort_tier="standard",
        tools_used=[],
        evidence_log="data/evidence/x.md",
        evidence_hash="a" * 64,
        info_cutoff=None,
        committed_at=committed_at,
        git_sha="deadbeef",
        supersedes=None,
        update_rationale=None,
        update_triggers=[
            UpdateTrigger(type="date", check="recheck", due=datetime(2026, 8, 1, tzinfo=UTC)),
        ],
    )


def _resolution(fid: str, question_id: str, outcome: str, resolved_at: datetime) -> ResolutionRecord:
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


def _two_question_ledger(state_root: Path) -> Ledger:
    """Two single-point resolved questions.

    Q1: p=0.7, outcome yes  -> system brier(0.7,1) = 0.09
    Q2: p=0.6, outcome no   -> system brier(0.6,0) = 0.36
    """
    led = Ledger(state_root)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = datetime(2026, 2, 1, tzinfo=UTC)
    led.append_forecast(
        _forecast(fid="F-20260101-001", question_id="Q-20260101-001", probability=0.7, committed_at=t0)
    )
    led.append_resolution(_resolution("F-20260101-001", "Q-20260101-001", "yes", r))
    led.append_forecast(
        _forecast(fid="F-20260101-002", question_id="Q-20260101-002", probability=0.6, committed_at=t0)
    )
    led.append_resolution(_resolution("F-20260101-002", "Q-20260101-002", "no", r))
    return led


# -- record / get -------------------------------------------------------------


def test_record_and_get_roundtrip(state_root: Path):
    path = record_baseline(state_root, "Q-20260101-001", "naive-claude", 0.3)
    assert path.exists()
    baselines = get_baselines(state_root, "Q-20260101-001")
    assert baselines["naive-claude"] == pytest.approx(0.3)


def test_record_baseline_path_layout(state_root: Path):
    path = record_baseline(state_root, "Q-20260101-001", "base-rate-only", 0.42)
    assert path == state_root / "data" / "benchmarks" / "Q-20260101-001" / "base-rate-only.json"


def test_always_half_auto_derivable(state_root: Path):
    # never recorded, but always available at 0.5
    baselines = get_baselines(state_root, "Q-does-not-exist")
    assert baselines["always-0.5"] == pytest.approx(0.5)


def test_get_baselines_multiple_names(state_root: Path):
    record_baseline(state_root, "Q-20260101-001", "naive-claude", 0.3)
    record_baseline(state_root, "Q-20260101-001", "market", 0.58)
    baselines = get_baselines(state_root, "Q-20260101-001")
    assert baselines["naive-claude"] == pytest.approx(0.3)
    assert baselines["market"] == pytest.approx(0.58)
    assert baselines["always-0.5"] == pytest.approx(0.5)


def test_record_baseline_overwrites_idempotently(state_root: Path):
    record_baseline(state_root, "Q-20260101-001", "market", 0.58)
    record_baseline(state_root, "Q-20260101-001", "market", 0.61)
    assert get_baselines(state_root, "Q-20260101-001")["market"] == pytest.approx(0.61)


# -- compare ------------------------------------------------------------------


def test_compare_hand_computed_mean_delta(state_root: Path):
    led = _two_question_ledger(state_root)
    # naive-claude: Q1=0.3 -> brier(0.3,1)=0.49 ; Q2=0.5 -> brier(0.5,0)=0.25
    record_baseline(state_root, "Q-20260101-001", "naive-claude", 0.3)
    record_baseline(state_root, "Q-20260101-002", "naive-claude", 0.5)

    cmp = compare(led, state_root, "naive-claude")
    # delta1 = 0.09 - 0.49 = -0.40 ; delta2 = 0.36 - 0.25 = 0.11 ; mean = -0.145
    assert isinstance(cmp, Comparison)
    assert cmp.baseline == "naive-claude"
    assert cmp.n == 2
    assert cmp.mean_delta_brier == pytest.approx(-0.145)
    assert cmp.ci_lo <= cmp.ci_hi
    # Q1 system better (0.09<0.49), Q2 system worse (0.36>0.25)
    assert cmp.win_rate == pytest.approx(0.5)


def test_compare_always_half_without_recording(state_root: Path):
    led = _two_question_ledger(state_root)
    # always-0.5 is auto-derivable, so compare works with no recorded baseline files
    cmp = compare(led, state_root, "always-0.5")
    # Q1: 0.09-0.25=-0.16 ; Q2: 0.36-0.25=0.11 ; mean=-0.025
    assert cmp.n == 2
    assert cmp.mean_delta_brier == pytest.approx(-0.025)
    assert cmp.win_rate == pytest.approx(0.5)


def test_compare_uses_time_weighted_stream_brier(state_root: Path):
    led = Ledger(state_root)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)  # 1 day later
    r = datetime(2026, 1, 11, tzinfo=UTC)  # 10 days after t0
    led.append_forecast(
        _forecast(fid="F-20260101-001", question_id="Q-20260101-001", stream_seq=0, probability=0.9, committed_at=t0)
    )
    led.append_forecast(
        _forecast(fid="F-20260101-002", question_id="Q-20260101-001", stream_seq=1, probability=0.1, committed_at=t1)
    )
    led.append_resolution(_resolution("F-20260101-002", "Q-20260101-001", "no", r))

    cmp = compare(led, state_root, "always-0.5")
    # stream: 0.9 for 1 day, 0.1 for 9 days, outcome 0
    # sys = 0.1*brier(0.9,0) + 0.9*brier(0.1,0) = 0.1*0.81 + 0.9*0.01 = 0.09
    # always-0.5: brier(0.5,0)=0.25 ; delta = 0.09-0.25 = -0.16
    assert cmp.n == 1
    assert cmp.mean_delta_brier == pytest.approx(-0.16)
    assert cmp.win_rate == pytest.approx(1.0)


def test_compare_skips_void_and_unresolved(state_root: Path):
    led = Ledger(state_root)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = datetime(2026, 2, 1, tzinfo=UTC)
    # resolved yes
    led.append_forecast(_forecast(fid="F-20260101-001", question_id="Q-20260101-001", probability=0.7, committed_at=t0))
    led.append_resolution(_resolution("F-20260101-001", "Q-20260101-001", "yes", r))
    # void -> excluded
    led.append_forecast(_forecast(fid="F-20260101-002", question_id="Q-20260101-002", probability=0.6, committed_at=t0))
    led.append_resolution(_resolution("F-20260101-002", "Q-20260101-002", "void", r))
    # unresolved -> excluded
    led.append_forecast(_forecast(fid="F-20260101-003", question_id="Q-20260101-003", probability=0.6, committed_at=t0))

    cmp = compare(led, state_root, "always-0.5")
    assert cmp.n == 1


def test_compare_skips_questions_without_that_baseline(state_root: Path):
    led = _two_question_ledger(state_root)
    # only Q1 has a naive-claude baseline recorded
    record_baseline(state_root, "Q-20260101-001", "naive-claude", 0.3)
    cmp = compare(led, state_root, "naive-claude")
    assert cmp.n == 1
    assert cmp.mean_delta_brier == pytest.approx(-0.40)


def test_compare_empty_ledger_returns_zero_n(state_root: Path):
    led = Ledger(state_root)
    cmp = compare(led, state_root, "naive-claude")
    assert cmp.n == 0
    assert cmp.win_rate == pytest.approx(0.0)


def test_compare_segment_filters_by_effort_tier(state_root: Path):
    led = Ledger(state_root)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = datetime(2026, 2, 1, tzinfo=UTC)
    q1 = _forecast(fid="F-20260101-001", question_id="Q-20260101-001", probability=0.7, committed_at=t0)
    q2 = _forecast(fid="F-20260101-002", question_id="Q-20260101-002", probability=0.6, committed_at=t0)
    q2 = q2.model_copy(update={"effort_tier": "deep"})
    led.append_forecast(q1)
    led.append_forecast(q2)
    led.append_resolution(_resolution("F-20260101-001", "Q-20260101-001", "yes", r))
    led.append_resolution(_resolution("F-20260101-002", "Q-20260101-002", "no", r))

    cmp = compare(led, state_root, "always-0.5", segment="deep")
    # only Q2 (deep): brier(0.6,0)=0.36 - 0.25 = 0.11
    assert cmp.n == 1
    assert cmp.mean_delta_brier == pytest.approx(0.11)
