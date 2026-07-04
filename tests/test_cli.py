"""CLI surface tests (§6.7) via click's CliRunner.

The CLI is the only sanctioned path from the LLM to on-disk state: it stamps
ids/timestamps/git SHA, clamps probabilities, enforces the update-trigger rule,
and returns machine-readable exit codes (0 = nothing to do, 10 = attention
needed). These tests exercise that contract end-to-end against an isolated
state root.

The golden fixtures under ``tests/fixtures/questions/`` are QuestionSpecs; the
forecast payloads a session would hand to ``oracle commit`` are built inline
here (a forecast is a different schema from the spec it references).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from click.testing import CliRunner

from oracle.cli import cli
from oracle.ledger import Ledger

FIXTURES = Path(__file__).parent / "fixtures" / "questions"


def _expected_sha() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _forecast_payload(qid: str, **overrides) -> dict:
    payload = {
        "question_id": qid,
        "probability": 0.62,
        "raw_pool": {"median": 0.62, "trimmed": 0.61, "geo_odds": 0.60},
        "ensemble": [
            {
                "kind": "method:base-rate",
                "probability": 0.55,
                "crux": "historical cut frequency near this macro backdrop",
            },
            {
                "kind": "evidence-slice:A",
                "probability": 0.68,
                "crux": "recent dovish FOMC communication",
            },
        ],
        "pool_method": "median",
        "resilience": "moderate",
        "ensemble_iqr": 0.13,
        "process_audit": {"spec_unambiguous": True, "arithmetic_verified": True},
        "effort_tier": "standard",
        "tools_used": ["fred"],
        "evidence_log": "data/evidence/Q-x.md",
        "evidence_hash": "deadbeef",
        "update_triggers": [
            {
                "type": "date",
                "check": "Read the March 2026 FOMC statement",
                "due": "2026-03-19T18:00:00Z",
            }
        ],
        # Caller-supplied stamps that the CLI MUST override:
        "committed_at": "1999-01-01T00:00:00Z",
        "git_sha": "CALLER-FORGED-SHA",
    }
    payload.update(overrides)
    return payload


def _invoke(runner, root, *args):
    return runner.invoke(cli, ["--root", str(root), *args])


def _create_question(runner, root, fixture="golden_binary.json") -> str:
    res = _invoke(runner, root, "question", "create", str(FIXTURES / fixture))
    assert res.exit_code == 0, res.output
    m = re.search(r"Created (Q-\d{8}-\d{3})", res.output)
    assert m, res.output
    return m.group(1)


def _write_forecast(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "forecast.json"
    p.write_text(json.dumps(payload))
    return p


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def test_status_empty_exits_zero(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "status")
    assert res.exit_code == 0
    assert "Empty ledger" in res.output


def test_status_with_due_resolution_exits_ten(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)  # deadline is in the past
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0

    res = _invoke(runner, state_root, "status")
    assert res.exit_code == 10, res.output
    assert "Due resolutions: 1" in res.output


# --------------------------------------------------------------------------- #
# question create + commit (dry-run then real)
# --------------------------------------------------------------------------- #
def test_commit_dry_run_does_not_write_then_real_commit_does(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))

    ledger_dir = state_root / "data" / "ledger"

    dry = _invoke(runner, state_root, "commit", str(fpath), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "[dry-run]" in dry.output
    assert not list(ledger_dir.glob("F-*.json"))

    real = _invoke(runner, state_root, "commit", str(fpath))
    assert real.exit_code == 0, real.output
    written = list(ledger_dir.glob("F-*.json"))
    assert len(written) == 1


def test_commit_stamps_time_and_sha_over_caller_values(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0

    rec = Ledger(state_root).all_forecasts()[0]
    assert rec.git_sha == _expected_sha()
    assert rec.git_sha != "CALLER-FORGED-SHA"
    # committed_at is stamped to "now", never the forged 1999 value.
    assert rec.committed_at.year != 1999
    assert rec.committed_at.tzinfo is not None
    assert rec.stream_seq == 0
    assert rec.stream_id == rec.id


def test_commit_clamps_probability(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid, probability=0.999))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0
    rec = Ledger(state_root).all_forecasts()[0]
    assert rec.probability == 0.99


def test_commit_requires_at_least_one_trigger(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid, update_triggers=[]))
    res = _invoke(runner, state_root, "commit", str(fpath))
    assert res.exit_code != 0
    assert "trigger" in res.output.lower()


def test_commit_fragile_requires_three_triggers(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    one = _forecast_payload(qid)["update_triggers"]
    fpath = _write_forecast(
        tmp_path, _forecast_payload(qid, resilience="fragile", update_triggers=one)
    )
    res = _invoke(runner, state_root, "commit", str(fpath))
    assert res.exit_code != 0, res.output
    assert "3" in res.output


def test_commit_second_forecast_appends_to_stream(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    f1 = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(f1)).exit_code == 0

    f2 = tmp_path / "f2.json"
    f2.write_text(json.dumps(_forecast_payload(qid, probability=0.7)))
    assert _invoke(runner, state_root, "commit", str(f2)).exit_code == 0

    stream = Ledger(state_root).stream(qid)
    assert [r.stream_seq for r in stream] == [0, 1]
    assert stream[0].stream_id == stream[1].stream_id


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #
def test_resolve_writes_resolution_and_scores(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0
    fid = Ledger(state_root).all_forecasts()[0].id

    res = _invoke(
        runner, state_root, "resolve", fid,
        "--outcome", "yes", "--evidence", "FOMC cut on 2026-03-18",
    )
    assert res.exit_code == 0, res.output
    resolution = Ledger(state_root).resolution_for(fid)
    assert resolution is not None
    assert resolution.outcome == "yes"
    assert "brier" in resolution.scores


def test_resolve_due_exit_codes(state_root, tmp_path):
    runner = CliRunner()
    # Nothing committed → nothing due → exit 0.
    assert _invoke(runner, state_root, "resolve", "--due").exit_code == 0

    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0
    # Deadline is in the past → one due → exit 10.
    due = _invoke(runner, state_root, "resolve", "--due")
    assert due.exit_code == 10, due.output


# --------------------------------------------------------------------------- #
# scoreboard / pnl / aggregate / baseline / stream / report / doctor
# --------------------------------------------------------------------------- #
def test_scoreboard_reports_insufficient_n_at_low_n(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "scoreboard")
    assert res.exit_code == 0, res.output
    assert "insufficient N" in res.output


def test_scoreboard_render_writes_file(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "scoreboard", "--render")
    assert res.exit_code == 0
    assert (state_root / "reports" / "scoreboard.md").exists()


def test_pnl_runs(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "pnl")
    assert res.exit_code == 0, res.output
    assert "P&L" in res.output


def test_aggregate_prints_three_pools(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "aggregate", "--probs", "0.6,0.7,0.55")
    assert res.exit_code == 0, res.output
    assert "median:" in res.output
    assert "geo_odds:" in res.output


def test_baseline_record_and_stream_show(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    rec = _invoke(runner, state_root, "baseline", "record", qid, "naive-claude", "0.5")
    assert rec.exit_code == 0, rec.output
    assert (state_root / "data" / "benchmarks" / qid / "naive-claude.json").exists()

    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0
    show = _invoke(runner, state_root, "stream", "show", qid)
    assert show.exit_code == 0, show.output
    assert "seq 0" in show.output


def test_report_renders_markdown(state_root, tmp_path):
    runner = CliRunner()
    qid = _create_question(runner, state_root)
    fpath = _write_forecast(tmp_path, _forecast_payload(qid))
    assert _invoke(runner, state_root, "commit", str(fpath)).exit_code == 0
    fid = Ledger(state_root).all_forecasts()[0].id
    res = _invoke(runner, state_root, "report", fid)
    assert res.exit_code == 0, res.output
    assert (state_root / "reports" / f"{fid}.md").exists()


def test_connectors_doctor_runs(state_root):
    runner = CliRunner()
    res = _invoke(runner, state_root, "connectors", "doctor")
    assert res.exit_code == 0, res.output
    assert "manifold" in res.output
