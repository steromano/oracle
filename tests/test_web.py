"""Tests for the Flask web layer (oracle.web).

Exercised entirely through Flask's test client — no live server, no network.
The web layer is a read-only view over the immutable ledger (§3.1: the Python
layer never runs the LLM forecast pipeline; forecasting is Claude-Code-driven).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from oracle.benchmarks import record_baseline
from oracle.ledger import Ledger
from oracle.models import (
    EnsembleMember,
    ForecastRecord,
    QuestionSpec,
    ResolutionRecord,
    UpdateTrigger,
)
from oracle.web import create_app

UTC = timezone.utc


def _forecast(
    *,
    fid: str,
    question_id: str,
    stream_seq: int = 0,
    probability: float = 0.63,
    committed_at: datetime,
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
        ],
        pool_method="median",
        market_price_used=None,
        calibration_map_id=None,
        resilience="moderate",
        ensemble_iqr=0.08,
        process_audit={"coherence": True},
        effort_tier="standard",
        tools_used=["manifold"],
        evidence_log="",
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


def _spec(qid: str, title: str) -> QuestionSpec:
    return QuestionSpec(
        id=qid,
        title=title,
        question_text="Will headline CPI exceed 3% YoY at the December print?",
        q_type="binary",
        thresholds=None,
        resolution_criteria="Resolves YES if the December CPI YoY print is > 3.0%.",
        resolution_source="Official statistics agency release",
        resolution_deadline=datetime(2026, 12, 31, 2, 0, tzinfo=UTC),
        edge_cases="Revisions do not change resolution.",
        domain="macro",
        horizon_days=180,
        linked_markets=[],
        origin="user",
        blind=False,
        sealed_snapshot=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by="stefano",
    )


def _write_spec(root: Path, spec: QuestionSpec) -> None:
    d = root / "data" / "questions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{spec.id}.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")


def _seed(state_root: Path) -> tuple[str, str]:
    """Seed one open question and one resolved question. Returns their qids."""
    led = Ledger(state_root)

    # Open question with a committed forecast + baselines.
    open_qid = "Q-20260101-001"
    _write_spec(state_root, _spec(open_qid, "Will inflation exceed target?"))
    led.append_forecast(
        _forecast(
            fid="F-20260101-001",
            question_id=open_qid,
            probability=0.63,
            committed_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    record_baseline(state_root, open_qid, "naive-claude", 0.5)
    record_baseline(state_root, open_qid, "base-rate-only", 0.4)
    record_baseline(state_root, open_qid, "market", 0.55)

    # Resolved question.
    res_qid = "Q-20260101-002"
    _write_spec(state_root, _spec(res_qid, "Will rates be cut in Q1?"))
    res_fid = "F-20260101-002"
    led.append_forecast(
        _forecast(
            fid=res_fid,
            question_id=res_qid,
            probability=0.40,
            committed_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    record_baseline(state_root, res_qid, "naive-claude", 0.5)
    led.append_resolution(
        ResolutionRecord(
            forecast_id=res_fid,
            question_id=res_qid,
            outcome="no",
            resolved_at=datetime(2026, 2, 1, tzinfo=UTC),
            resolution_evidence="official source",
            scores={"stream_brier": 0.16},
            baseline_scores={},
            pnl=None,
            spec_defect_audit=None,
        )
    )
    return open_qid, res_qid


def test_index_lists_questions_with_status(state_root: Path):
    open_qid, res_qid = _seed(state_root)
    client = create_app(state_root).test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Will inflation exceed target?" in body
    assert "Will rates be cut in Q1?" in body
    assert "Open" in body
    assert "Resolved" in body
    # Resolution cell shows outcome + stream_brier.
    assert "0.1600" in body


def test_question_page_shows_history_and_report(state_root: Path):
    open_qid, _ = _seed(state_root)
    client = create_app(state_root).test_client()

    resp = client.get(f"/q/{open_qid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Update-history element ('initial' rationale for seq 0).
    assert "Update history" in body
    assert "initial" in body
    # Report content rendered from markdown (headline / benchmark line).
    assert "naive-claude" in body
    assert "moderate" in body


def test_unknown_question_404(state_root: Path):
    _seed(state_root)
    client = create_app(state_root).test_client()
    assert client.get("/q/Q-does-not-exist").status_code == 404
