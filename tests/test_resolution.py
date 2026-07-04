"""Tests for oracle.resolution (Task 7).

Covers:
- due_forecasts excludes already-resolved questions and future deadlines.
- due_triggers surfaces only triggers whose ``due <= now`` (and skips
  triggers with ``due is None``).
- build_resolution computes time-averaged stream_brier plus per-baseline
  scores and a market paper-trade for a two-point stream.
- VOID sets spec_defect_audit, empties scores, and skips pnl.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from oracle.benchmarks import record_baseline
from oracle.ledger import Ledger
from oracle.models import ForecastRecord, QuestionSpec, ResolutionRecord, UpdateTrigger
from oracle.resolution import build_resolution, due_forecasts, due_triggers

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def make_forecast(
    fid: str,
    question_id: str,
    *,
    seq: int = 0,
    probability: float = 0.6,
    committed_at: datetime,
    triggers: list[UpdateTrigger] | None = None,
) -> ForecastRecord:
    return ForecastRecord(
        id=fid,
        question_id=question_id,
        stream_id=question_id,
        stream_seq=seq,
        probability=probability,
        raw_pool={"median": probability},
        ensemble=[],
        pool_method="median",
        resilience="moderate",
        ensemble_iqr=0.0,
        process_audit={},
        effort_tier="standard",
        tools_used=[],
        evidence_log=f"data/evidence/{fid}.md",
        evidence_hash="0" * 64,
        committed_at=committed_at,
        git_sha="deadbeef",
        update_triggers=triggers or [],
    )


def make_spec(qid: str, *, deadline: datetime) -> QuestionSpec:
    return QuestionSpec(
        id=qid,
        title=f"title {qid}",
        question_text=f"question {qid}?",
        q_type="binary",
        resolution_criteria="the stranger test",
        resolution_source="official",
        resolution_deadline=deadline,
        edge_cases="void if source stops",
        domain="macro",
        horizon_days=10,
        origin="user",
        created_at=deadline - timedelta(days=10),
        created_by="tester",
    )


def write_spec(questions_dir: Path, spec: QuestionSpec) -> None:
    questions_dir.mkdir(parents=True, exist_ok=True)
    (questions_dir / f"{spec.id}.json").write_text(
        spec.model_dump_json(indent=2), encoding="utf-8"
    )


def write_baseline(root: Path, qid: str, name: str, p: float) -> None:
    record_baseline(root, qid, name, p)


def write_resolution(ledger: Ledger, fid: str, qid: str, now: datetime) -> None:
    ledger.append_resolution(
        ResolutionRecord(
            forecast_id=fid,
            question_id=qid,
            outcome="yes",
            resolved_at=now,
            resolution_evidence="done",
            scores={"brier": 0.0, "stream_brier": 0.0, "log": 0.0},
            baseline_scores={},
        )
    )


# --------------------------------------------------------------------------- #
# due_forecasts
# --------------------------------------------------------------------------- #
def test_due_forecasts_excludes_future_and_resolved(tmp_path: Path):
    root = tmp_path
    questions_dir = root / "data" / "questions"
    ledger = Ledger(root)
    now = datetime(2026, 7, 5, tzinfo=UTC)

    # Q-A: past deadline, unresolved -> DUE
    write_spec(questions_dir, make_spec("Q-A", deadline=now - timedelta(days=1)))
    ledger.append_forecast(
        make_forecast("F-A", "Q-A", committed_at=now - timedelta(days=10))
    )

    # Q-B: future deadline, unresolved -> not due
    write_spec(questions_dir, make_spec("Q-B", deadline=now + timedelta(days=5)))
    ledger.append_forecast(
        make_forecast("F-B", "Q-B", committed_at=now - timedelta(days=1))
    )

    # Q-C: past deadline but already resolved -> not due
    write_spec(questions_dir, make_spec("Q-C", deadline=now - timedelta(days=2)))
    ledger.append_forecast(
        make_forecast("F-C", "Q-C", committed_at=now - timedelta(days=10))
    )
    write_resolution(ledger, "F-C", "Q-C", now)

    due = due_forecasts(ledger, questions_dir, now)
    assert due == ["F-A"]


def test_due_forecasts_returns_latest_stream_point(tmp_path: Path):
    root = tmp_path
    questions_dir = root / "data" / "questions"
    ledger = Ledger(root)
    now = datetime(2026, 7, 5, tzinfo=UTC)

    write_spec(questions_dir, make_spec("Q-A", deadline=now - timedelta(days=1)))
    ledger.append_forecast(
        make_forecast("F-A0", "Q-A", seq=0, committed_at=now - timedelta(days=10))
    )
    ledger.append_forecast(
        make_forecast("F-A1", "Q-A", seq=1, committed_at=now - timedelta(days=3))
    )

    assert due_forecasts(ledger, questions_dir, now) == ["F-A1"]


# --------------------------------------------------------------------------- #
# due_triggers
# --------------------------------------------------------------------------- #
def test_due_triggers_only_past_due(tmp_path: Path):
    root = tmp_path
    ledger = Ledger(root)
    now = datetime(2026, 7, 5, tzinfo=UTC)

    triggers = [
        UpdateTrigger(type="date", check="ripe", due=now - timedelta(days=1)),
        UpdateTrigger(type="date", check="future", due=now + timedelta(days=1)),
        UpdateTrigger(type="event", check="no-due", due=None),
    ]
    ledger.append_forecast(
        make_forecast(
            "F-A", "Q-A", committed_at=now - timedelta(days=5), triggers=triggers
        )
    )

    surfaced = due_triggers(ledger, now)
    assert len(surfaced) == 1
    fid, trig = surfaced[0]
    assert fid == "F-A"
    assert trig.check == "ripe"


def test_due_triggers_skips_resolved(tmp_path: Path):
    root = tmp_path
    ledger = Ledger(root)
    now = datetime(2026, 7, 5, tzinfo=UTC)

    triggers = [UpdateTrigger(type="date", check="ripe", due=now - timedelta(days=1))]
    ledger.append_forecast(
        make_forecast(
            "F-A", "Q-A", committed_at=now - timedelta(days=5), triggers=triggers
        )
    )
    write_resolution(ledger, "F-A", "Q-A", now)

    assert due_triggers(ledger, now) == []


# --------------------------------------------------------------------------- #
# build_resolution
# --------------------------------------------------------------------------- #
def test_build_resolution_two_point_stream(tmp_path: Path):
    root = tmp_path
    ledger = Ledger(root)

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 11, tzinfo=UTC)
    now = datetime(2026, 1, 21, tzinfo=UTC)

    ledger.append_forecast(make_forecast("F-0", "Q-1", seq=0, probability=0.6, committed_at=t0))
    ledger.append_forecast(make_forecast("F-1", "Q-1", seq=1, probability=0.8, committed_at=t1))

    write_baseline(root, "Q-1", "naive-claude", 0.3)
    write_baseline(root, "Q-1", "market", 0.5)

    rec = build_resolution(ledger, root, "F-1", "yes", "resolved from source", now)

    assert isinstance(rec, ResolutionRecord)
    assert rec.forecast_id == "F-1"
    assert rec.question_id == "Q-1"
    assert rec.outcome == "yes"
    assert rec.resolved_at == now
    assert rec.spec_defect_audit is None

    # system scores: two 10-day intervals, equal weight.
    # stream_brier = 0.5*(0.6-1)^2 + 0.5*(0.8-1)^2 = 0.5*0.16 + 0.5*0.04 = 0.10
    assert rec.scores["stream_brier"] == pytest.approx(0.10)
    # final-point brier uses the latest stream point (0.8)
    assert rec.scores["brier"] == pytest.approx(0.04)
    assert rec.scores["log"] == pytest.approx(-math.log(0.8))

    # baselines scored as single held-constant points
    assert rec.baseline_scores["naive-claude"]["brier"] == pytest.approx(0.49)
    assert rec.baseline_scores["naive-claude"]["stream_brier"] == pytest.approx(0.49)
    assert rec.baseline_scores["naive-claude"]["log"] == pytest.approx(-math.log(0.3))
    assert rec.baseline_scores["market"]["brier"] == pytest.approx(0.25)

    # pnl vs the market baseline: p_oracle=0.8, p_market=0.5, outcome=1
    # edge>0 -> yes; full_kelly=0.6; stake=0.25*0.6=0.15; net_odds=1 -> payoff=0.15
    assert rec.pnl is not None
    assert rec.pnl.direction == "yes"
    assert rec.pnl.stake == pytest.approx(0.15)
    assert rec.pnl.payoff == pytest.approx(0.15)


def test_build_resolution_void(tmp_path: Path):
    root = tmp_path
    ledger = Ledger(root)
    now = datetime(2026, 1, 21, tzinfo=UTC)

    ledger.append_forecast(
        make_forecast("F-0", "Q-1", seq=0, probability=0.6, committed_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    write_baseline(root, "Q-1", "market", 0.5)

    rec = build_resolution(ledger, root, "F-0", "void", "ambiguous spec", now)

    assert rec.outcome == "void"
    assert rec.pnl is None
    assert rec.scores == {}
    assert rec.baseline_scores == {}
    assert rec.spec_defect_audit is not None
    assert "F-0" in rec.spec_defect_audit
    assert rec.spec_defect_audit.startswith("knowledge/audits/")


def test_build_resolution_no_market_baseline_skips_pnl(tmp_path: Path):
    root = tmp_path
    ledger = Ledger(root)
    now = datetime(2026, 1, 21, tzinfo=UTC)

    ledger.append_forecast(
        make_forecast("F-0", "Q-1", seq=0, probability=0.7, committed_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    write_baseline(root, "Q-1", "naive-claude", 0.4)

    rec = build_resolution(ledger, root, "F-0", "no", "resolved no", now)

    assert rec.pnl is None
    assert rec.scores["brier"] == pytest.approx((0.7 - 0) ** 2)
    assert rec.baseline_scores["naive-claude"]["brier"] == pytest.approx((0.4 - 0) ** 2)
