"""Tests for the append-only ledger store (Task 5, §6.1 / §7.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle.ledger import Ledger
from oracle.models import (
    EnsembleMember,
    ForecastRecord,
    ResolutionRecord,
    TradeResult,
    UpdateTrigger,
)

UTC = timezone.utc


def _forecast(
    *,
    fid: str = "F-20260705-001",
    question_id: str = "Q-20260705-001",
    stream_id: str = "S-20260705-001",
    stream_seq: int = 0,
    committed_at: datetime | None = None,
    supersedes: str | None = None,
) -> ForecastRecord:
    return ForecastRecord(
        id=fid,
        question_id=question_id,
        stream_id=stream_id,
        stream_seq=stream_seq,
        probability=0.62,
        raw_pool={"median": 0.60, "trimmed": 0.61, "geo_odds": 0.63},
        ensemble=[
            EnsembleMember(kind="method:base-rate", probability=0.55, crux="historical rate"),
        ],
        pool_method="geo_odds",
        market_price_used=0.58,
        calibration_map_id=None,
        resilience="moderate",
        ensemble_iqr=0.08,
        process_audit={"coherence": True},
        effort_tier="standard",
        tools_used=["manifold"],
        evidence_log="data/evidence/x.md",
        evidence_hash="a" * 64,
        info_cutoff=None,
        committed_at=committed_at or datetime(2026, 7, 5, 3, 30, tzinfo=UTC),
        git_sha="deadbeef",
        supersedes=supersedes,
        update_rationale=None if supersedes is None else "new evidence",
        update_triggers=[
            UpdateTrigger(type="date", check="re-check", due=datetime(2026, 7, 20, tzinfo=UTC)),
        ],
    )


def _resolution(fid: str = "F-20260705-001", question_id: str = "Q-20260705-001") -> ResolutionRecord:
    return ResolutionRecord(
        forecast_id=fid,
        question_id=question_id,
        outcome="yes",
        resolved_at=datetime(2026, 9, 30, 5, 0, tzinfo=UTC),
        resolution_evidence="RBA announcement",
        scores={"brier": 0.14, "stream_brier": 0.16, "log": 0.42},
        baseline_scores={"always-0.5": {"brier": 0.25}},
        pnl=TradeResult(
            direction="yes", stake=0.1, entry_price=0.58, payoff=0.072, log_wealth_delta=0.03
        ),
        spec_defect_audit=None,
    )


def test_append_and_get_roundtrip(state_root: Path):
    led = Ledger(state_root)
    rec = _forecast()
    path = led.append_forecast(rec)
    assert path.exists()
    assert led.get_forecast("F-20260705-001") == rec


def test_append_forecast_refuses_overwrite(state_root: Path):
    led = Ledger(state_root)
    led.append_forecast(_forecast())
    with pytest.raises(FileExistsError):
        led.append_forecast(_forecast())


def test_append_resolution_roundtrip_and_no_overwrite(state_root: Path):
    led = Ledger(state_root)
    led.append_forecast(_forecast())
    res = _resolution()
    led.append_resolution(res)
    assert led.resolution_for("F-20260705-001") == res
    with pytest.raises(FileExistsError):
        led.append_resolution(res)


def test_resolution_for_missing_returns_none(state_root: Path):
    led = Ledger(state_root)
    led.append_forecast(_forecast())
    assert led.resolution_for("F-20260705-001") is None


def test_get_forecast_missing_raises(state_root: Path):
    led = Ledger(state_root)
    with pytest.raises(FileNotFoundError):
        led.get_forecast("F-20260705-999")


def test_stream_is_seq_ordered(state_root: Path):
    led = Ledger(state_root)
    # append out of order
    led.append_forecast(_forecast(fid="F-20260705-002", stream_seq=1))
    led.append_forecast(_forecast(fid="F-20260705-001", stream_seq=0))
    led.append_forecast(_forecast(fid="F-20260705-003", stream_seq=2))
    stream = led.stream("Q-20260705-001")
    assert [r.stream_seq for r in stream] == [0, 1, 2]
    assert [r.id for r in stream] == [
        "F-20260705-001",
        "F-20260705-002",
        "F-20260705-003",
    ]


def test_stream_only_includes_matching_question(state_root: Path):
    led = Ledger(state_root)
    led.append_forecast(_forecast(fid="F-20260705-001", question_id="Q-20260705-001"))
    led.append_forecast(
        _forecast(
            fid="F-20260705-002",
            question_id="Q-20260705-002",
            stream_id="S-20260705-002",
        )
    )
    assert [r.id for r in led.stream("Q-20260705-001")] == ["F-20260705-001"]


def test_supersedes_correction_coexists(state_root: Path):
    led = Ledger(state_root)
    original = _forecast(fid="F-20260705-001", stream_seq=0)
    correction = _forecast(
        fid="F-20260705-002", stream_seq=1, supersedes="F-20260705-001"
    )
    led.append_forecast(original)
    led.append_forecast(correction)
    # both remain on disk (append-only, corrections never mutate)
    assert led.get_forecast("F-20260705-001") == original
    assert led.get_forecast("F-20260705-002") == correction
    assert led.get_forecast("F-20260705-002").supersedes == "F-20260705-001"


def test_all_forecasts_excludes_resolutions(state_root: Path):
    led = Ledger(state_root)
    led.append_forecast(_forecast(fid="F-20260705-001"))
    led.append_forecast(_forecast(fid="F-20260705-002", stream_seq=1))
    led.append_resolution(_resolution("F-20260705-001"))
    ids = sorted(r.id for r in led.all_forecasts())
    assert ids == ["F-20260705-001", "F-20260705-002"]


def test_next_seq_increments_across_same_day_writes(state_root: Path):
    led = Ledger(state_root)
    date = datetime(2026, 7, 5, tzinfo=UTC)
    assert led.next_seq("F", date) == 1
    led.append_forecast(_forecast(fid="F-20260705-001"))
    assert led.next_seq("F", date) == 2
    led.append_forecast(_forecast(fid="F-20260705-002", stream_seq=1))
    assert led.next_seq("F", date) == 3
    # a different date resets to 1
    assert led.next_seq("F", datetime(2026, 7, 6, tzinfo=UTC)) == 1


def test_backtest_namespace_isolated_from_live(state_root: Path):
    live = Ledger(state_root, namespace="live")
    backtest = Ledger(state_root, namespace="backtest")
    live.append_forecast(_forecast(fid="F-20260705-001"))
    backtest.append_forecast(_forecast(fid="F-20260705-001"))
    # backtest file lives under data/ledger/backtest and does not pollute live
    assert (state_root / "data" / "ledger" / "F-20260705-001.json").exists()
    assert (
        state_root / "data" / "ledger" / "backtest" / "F-20260705-001.json"
    ).exists()
    assert len(live.all_forecasts()) == 1
    assert len(backtest.all_forecasts()) == 1
    # live scan must not descend into the backtest subdirectory
    assert live.next_seq("F", datetime(2026, 7, 5, tzinfo=UTC)) == 2


def test_invalid_namespace_rejected(state_root: Path):
    with pytest.raises(ValueError):
        Ledger(state_root, namespace="bogus")
