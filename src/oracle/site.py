"""Static HTML site generator over the Oracle ledger — no server required.

``oracle site`` renders self-contained HTML into ``<root>/site/``: ``index.html``
(the ledger) plus one ``<qid>.html`` per question (update history + the embedded
self-contained report). Open ``site/index.html`` in a browser; regenerate any
time (e.g. from the nightly cron). Per §3.1 this is presentation only — it never
runs the LLM forecast pipeline; forecasting is Claude-Code-driven.
"""

from __future__ import annotations

from pathlib import Path

import markdown as _markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from oracle.benchmarks import get_baselines
from oracle.ledger import Ledger
from oracle.models import QuestionSpec
from oracle.report import render_report

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "web"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _questions_dir(root: Path) -> Path:
    return Path(root) / "data" / "questions"


def _load_spec(root: Path, qid: str) -> QuestionSpec | None:
    path = _questions_dir(root) / f"{qid}.json"
    if not path.exists():
        return None
    return QuestionSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _ledger_rows(root: Path, ledger: Ledger) -> list[dict]:
    latest: dict[str, object] = {}
    for rec in ledger.all_forecasts():
        cur = latest.get(rec.question_id)
        if cur is None or rec.stream_seq > cur.stream_seq:
            latest[rec.question_id] = rec

    rows: list[dict] = []
    for qid, rec in latest.items():
        spec = _load_spec(root, qid)
        baselines = get_baselines(root, qid)
        resolution = ledger.resolution_for(rec.id)
        resolution_text = ""
        if resolution is not None:
            brier = resolution.scores.get("stream_brier")
            resolution_text = (
                f"{resolution.outcome} (Brier {brier:.4f})"
                if brier is not None
                else resolution.outcome
            )
        rows.append(
            {
                "qid": qid,
                "title": spec.title if spec else qid,
                "origin": spec.origin if spec else "user",
                "blind": spec.blind if spec else False,
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
    return rows


def _forecast_page(root: Path, ledger: Ledger, qid: str) -> str | None:
    stream = ledger.stream(qid)
    if not stream:
        return None
    spec = _load_spec(root, qid)
    if spec is None:
        return None
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
        ev_path = Path(root) / rec.evidence_log
        if ev_path.is_file():
            evidence_body = ev_path.read_text(encoding="utf-8")
    md = render_report(rec, spec, baselines, stream, evidence_body=evidence_body)
    report_html = _markdown.markdown(md, extensions=["tables", "fenced_code"])
    return _ENV.get_template("forecast.html").render(
        spec=spec, history=history, report_html=report_html
    )


def render_site(root: Path, out_dir: Path | None = None) -> Path:
    """Render the static site into ``out_dir`` (default ``<root>/site``)."""
    root = Path(root)
    out_dir = Path(out_dir) if out_dir is not None else root / "site"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root)

    rows = _ledger_rows(root, ledger)
    (out_dir / "index.html").write_text(
        _ENV.get_template("index.html").render(rows=rows), encoding="utf-8"
    )
    for qid in {r["qid"] for r in rows}:
        html = _forecast_page(root, ledger, qid)
        if html is not None:
            (out_dir / f"{qid}.html").write_text(html, encoding="utf-8")
    return out_dir
