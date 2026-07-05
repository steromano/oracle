"""Tiny read-only Flask app over the Oracle ledger (§3.1-compatible).

This is a *presentation* layer only. Per the architectural constraint in §3.1
(Python is deterministic-only), the web layer NEVER runs the LLM forecast
pipeline — forecasting is entirely Claude-Code-driven. The app just reads the
immutable ledger/benchmarks/report modules to display state.

Routes:

* ``GET /``          — one row per question (latest stream point).
* ``GET /q/<qid>``   — spec summary, update history, and the self-contained report.
"""

from __future__ import annotations

from pathlib import Path

import markdown as _markdown
from flask import Flask, abort, render_template

from oracle.benchmarks import get_baselines
from oracle.ledger import Ledger
from oracle.models import QuestionSpec
from oracle.report import render_report

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "web"


def _questions_dir(root: Path) -> Path:
    return Path(root) / "data" / "questions"


def _load_spec(root: Path, qid: str) -> QuestionSpec | None:
    path = _questions_dir(root) / f"{qid}.json"
    if not path.exists():
        return None
    return QuestionSpec.model_validate_json(path.read_text(encoding="utf-8"))


def create_app(root: Path) -> Flask:
    root = Path(root)
    app = Flask(__name__, template_folder=str(_TEMPLATE_DIR))
    app.config["ORACLE_ROOT"] = root

    @app.route("/")
    def index():
        ledger = Ledger(root)
        # Latest stream point per question_id.
        latest: dict[str, object] = {}
        for rec in ledger.all_forecasts():
            cur = latest.get(rec.question_id)
            if cur is None or rec.stream_seq > cur.stream_seq:
                latest[rec.question_id] = rec

        rows = []
        for qid, rec in latest.items():
            spec = _load_spec(root, qid)
            baselines = get_baselines(root, qid)
            resolution = ledger.resolution_for(rec.id)
            resolution_text = ""
            if resolution is not None:
                brier = resolution.scores.get("stream_brier")
                if brier is not None:
                    resolution_text = f"{resolution.outcome} (Brier {brier:.4f})"
                else:
                    resolution_text = resolution.outcome
            rows.append(
                {
                    "qid": qid,
                    "title": spec.title if spec else qid,
                    "domain": spec.domain if spec else "",
                    "status": "Resolved" if resolution is not None else "Open",
                    "oracle_pct": f"{rec.probability * 100:.0f}%",
                    "naive_claude": baselines.get("naive-claude"),
                    "base_rate_only": baselines.get("base-rate-only"),
                    "market": baselines.get("market"),
                    "resolution": resolution_text,
                    "deadline": (
                        spec.resolution_deadline.date().isoformat() if spec else ""
                    ),
                }
            )
        rows.sort(key=lambda r: r["qid"])
        return render_template("index.html", rows=rows)

    @app.route("/q/<qid>")
    def question(qid: str):
        ledger = Ledger(root)
        stream = ledger.stream(qid)
        if not stream:
            abort(404)
        spec = _load_spec(root, qid)
        if spec is None:
            abort(404)

        rec = stream[-1]
        history = [
            {
                "seq": s.stream_seq,
                "pct": f"{s.probability * 100:.0f}%",
                "committed_at": s.committed_at.isoformat(),
                "rationale": s.update_rationale or "initial",
            }
            for s in stream
        ]

        baselines = get_baselines(root, qid)
        evidence_body = ""
        if rec.evidence_log:
            ev_path = root / rec.evidence_log
            if ev_path.is_file():
                evidence_body = ev_path.read_text(encoding="utf-8")
        md = render_report(rec, spec, baselines, stream, evidence_body=evidence_body)
        report_html = _markdown.markdown(md, extensions=["tables", "fenced_code"])

        return render_template(
            "forecast.html",
            spec=spec,
            history=history,
            report_html=report_html,
        )

    return app
