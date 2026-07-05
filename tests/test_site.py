"""Tests for the static site generator (oracle.site).

Renders into a temp directory and inspects the generated HTML files — no server,
no network. The site is a read-only view over the immutable ledger (§3.1: the
Python layer never runs the LLM forecast pipeline; forecasting is Claude-Code-driven).
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
from oracle.site import render_site

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


def _spec(qid: str, title: str, origin: str = "user") -> QuestionSpec:
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
        origin=origin,
        blind=(origin == "import"),
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
    _seed(state_root)
    out = render_site(state_root, state_root / "site")
    body = (out / "index.html").read_text(encoding="utf-8")
    assert "Will inflation exceed target?" in body
    assert "Will rates be cut in Q1?" in body
    assert "Open" in body
    assert "Resolved" in body
    # Resolution cell shows outcome + stream_brier.
    assert "0.1600" in body
    # Rows link to per-question static pages.
    assert "Q-20260101-001.html" in body


def test_forecast_page_generated(state_root: Path):
    open_qid, _ = _seed(state_root)
    out = render_site(state_root, state_root / "site")
    page = out / f"{open_qid}.html"
    assert page.is_file()
    body = page.read_text(encoding="utf-8")
    assert "Update history" in body
    assert "initial" in body  # seq-0 rationale
    # Embedded self-contained report content.
    assert "LLM" in body
    assert "moderate" in body
    # Static back-link to the ledger.
    assert 'href="index.html"' in body


def test_ledger_separates_user_and_import(state_root: Path):
    led = Ledger(state_root)
    _write_spec(state_root, _spec("Q-20260101-010", "A user deployment question", origin="user"))
    led.append_forecast(
        _forecast(fid="F-20260101-010", question_id="Q-20260101-010",
                  committed_at=datetime(2026, 1, 2, tzinfo=UTC))
    )
    _write_spec(state_root, _spec("Q-20260101-011", "A blind imported question", origin="import"))
    led.append_forecast(
        _forecast(fid="F-20260101-011", question_id="Q-20260101-011",
                  committed_at=datetime(2026, 1, 2, tzinfo=UTC))
    )
    body = (render_site(state_root, state_root / "site") / "index.html").read_text(encoding="utf-8")
    # Two labelled sections exist.
    assert "deployment" in body and "testing" in body.lower()
    # The user question appears before the import section header; the import after it.
    import_header_pos = body.find("Market imports")
    assert 0 < body.find("A user deployment question") < import_header_pos
    assert body.find("A blind imported question") > import_header_pos


def test_render_site_prunes_orphaned_pages(state_root: Path):
    _seed(state_root)
    out = state_root / "site"
    out.mkdir(parents=True, exist_ok=True)
    stale = out / "Q-20200101-999.html"  # a question no longer in the ledger
    stale.write_text("orphan", encoding="utf-8")
    render_site(state_root, out)
    assert not stale.exists()  # pruned
    assert (out / "Q-20260101-001.html").exists()  # current page kept


def test_no_page_for_unknown_question(state_root: Path):
    _seed(state_root)
    out = render_site(state_root, state_root / "site")
    assert not (out / "Q-does-not-exist.html").exists()
    # Exactly the two seeded questions get pages.
    pages = sorted(p.name for p in out.glob("Q-*.html"))
    assert pages == ["Q-20260101-001.html", "Q-20260101-002.html"]
