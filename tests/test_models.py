"""Tests for the Oracle data schemas (Task 1, §7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from oracle.models import (
    EnsembleMember,
    ForecastRecord,
    MarketLink,
    QuestionSpec,
    ResolutionRecord,
    TradeResult,
    UpdateTrigger,
    new_forecast_id,
    new_question_id,
)

UTC = timezone.utc


def _full_forecast() -> ForecastRecord:
    return ForecastRecord(
        id="F-20260705-001",
        question_id="Q-20260705-001",
        stream_id="S-20260705-001",
        stream_seq=0,
        probability=0.62,
        raw_pool={"median": 0.60, "trimmed": 0.61, "geo_odds": 0.63},
        ensemble=[
            EnsembleMember(kind="method:base-rate", probability=0.55, crux="historical rate"),
            EnsembleMember(kind="model:openrouter/x", probability=0.70, crux="recent momentum"),
        ],
        pool_method="geo_odds",
        market_price_used=0.58,
        calibration_map_id="cal-20260705-001",
        resilience="moderate",
        ensemble_iqr=0.08,
        process_audit={"coherence": True, "leakage_check": True},
        effort_tier="standard",
        tools_used=["manifold", "fred"],
        evidence_log="data/evidence/F-20260705-001.md",
        evidence_hash="a" * 64,
        info_cutoff=datetime(2026, 7, 1, tzinfo=UTC),
        committed_at=datetime(2026, 7, 5, 3, 30, tzinfo=UTC),
        git_sha="deadbeef",
        supersedes=None,
        update_rationale=None,
        update_triggers=[
            UpdateTrigger(
                type="date",
                check="re-check on FOMC day",
                due=datetime(2026, 7, 20, tzinfo=UTC),
            )
        ],
    )


def test_forecast_record_json_roundtrip():
    rec = _full_forecast()
    dumped = rec.model_dump_json()
    restored = ForecastRecord.model_validate_json(dumped)
    assert restored == rec
    # Defaults present in Task 1 spec
    assert restored.variant == "control"
    assert restored.blind_violated is False


def test_datetime_is_tz_aware_after_naive_input():
    """A naive datetime must be coerced to tz-aware UTC (not stored naive)."""
    spec = QuestionSpec(
        id="Q-20260705-001",
        title="Rate cut?",
        question_text="Will the RBA cut by September 2026?",
        q_type="binary",
        thresholds=None,
        resolution_criteria="Official RBA cash-rate decision.",
        resolution_source="RBA website",
        resolution_deadline=datetime(2026, 9, 30, 0, 0),  # naive
        edge_cases="none",
        domain="macro",
        horizon_days=87,
        linked_markets=[MarketLink(platform="manifold", market_id="abc", price_at_creation=0.4)],
        origin="user",
        created_at=datetime(2026, 7, 5, 3, 0),  # naive
        created_by="stefano",
    )
    assert spec.resolution_deadline.tzinfo is not None
    assert spec.resolution_deadline.utcoffset() == timedelta(0)
    assert spec.created_at.tzinfo is not None
    assert spec.created_at.utcoffset() == timedelta(0)


def test_non_utc_aware_datetime_normalized_to_utc():
    """A tz-aware but non-UTC datetime is converted to the same instant in UTC."""
    syd = timezone(timedelta(hours=10))
    data = _full_forecast().model_dump()
    data["committed_at"] = datetime(2026, 7, 5, 13, 30, tzinfo=syd)
    committed = ForecastRecord.model_validate(data)
    # 13:30 +10:00 == 03:30 UTC
    assert committed.committed_at == datetime(2026, 7, 5, 3, 30, tzinfo=UTC)
    assert committed.committed_at.utcoffset() == timedelta(0)


def test_new_forecast_id():
    assert new_forecast_id(datetime(2026, 7, 5, 3, 30, tzinfo=UTC), 1) == "F-20260705-001"


def test_new_question_id():
    assert new_question_id(datetime(2026, 7, 5, tzinfo=UTC), 12) == "Q-20260705-012"
    assert new_question_id(datetime(2026, 12, 31, tzinfo=UTC), 999) == "Q-20261231-999"


def test_resolution_record_roundtrip():
    rec = ResolutionRecord(
        forecast_id="F-20260705-001",
        question_id="Q-20260705-001",
        outcome="yes",
        resolved_at=datetime(2026, 9, 30, 5, 0, tzinfo=UTC),
        resolution_evidence="RBA announcement",
        scores={"brier": 0.14, "stream_brier": 0.16, "log": 0.42},
        baseline_scores={"naive-claude": {"brier": 0.22}, "always-0.5": {"brier": 0.25}},
        pnl=TradeResult(
            direction="yes", stake=0.1, entry_price=0.58, payoff=0.072, log_wealth_delta=0.03
        ),
        spec_defect_audit=None,
    )
    restored = ResolutionRecord.model_validate_json(rec.model_dump_json())
    assert restored == rec
    assert restored.resolved_at.utcoffset() == timedelta(0)


def test_optional_datetime_none_allowed():
    rec = _full_forecast().model_copy(update={"info_cutoff": None})
    assert rec.info_cutoff is None
