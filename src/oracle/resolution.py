"""Due-date logic and resolution-record construction (§5.11, §7.3).

This module is the deterministic core of the ``resolve`` workflow. It answers
two "what is due?" questions and builds the :class:`ResolutionRecord` that the
CLI later appends to the ledger:

- :func:`due_forecasts` — questions whose deadline has passed and that have no
  resolution yet (the latest stream point is returned as the thing to resolve).
- :func:`due_triggers` — update triggers on live streams whose ``due`` moment
  has arrived (§5.14), so ``oracle status`` can surface them.
- :func:`build_resolution` — given an outcome, compute the system's Brier /
  time-averaged stream-Brier / log scores, the same scores for every recorded
  baseline, and a paper-trade P&L against the ``market`` baseline (§9.4). VOID
  resolutions carry no scores — they instead point at a spec-defect audit note
  (§5.12).

All scoring math is delegated to :mod:`oracle.scoring`; this module never
computes a score itself. Baselines are read through :mod:`oracle.benchmarks`
when available, falling back to the documented on-disk store otherwise so the
resolve loop stays testable in isolation.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from oracle.ledger import Ledger
from oracle.models import (
    ForecastRecord,
    QuestionSpec,
    ResolutionRecord,
    UpdateTrigger,
)
from oracle.scoring import brier, log_score, paper_trade, stream_brier

# yes/no map to the 1/0 outcomes the scoring layer expects; void has no score.
_OUTCOME_INT = {"yes": 1, "no": 0}
# Baseline name whose price drives the paper-trade P&L track (§5.13, §9.4).
_MARKET_BASELINE = "market"


# --------------------------------------------------------------------------- #
# due-date logic
# --------------------------------------------------------------------------- #
def _streams_by_question(ledger: Ledger) -> dict[str, list[ForecastRecord]]:
    """Group every forecast by question id, each list seq-ordered."""
    by_q: dict[str, list[ForecastRecord]] = {}
    for rec in ledger.all_forecasts():
        by_q.setdefault(rec.question_id, []).append(rec)
    for recs in by_q.values():
        recs.sort(key=lambda r: r.stream_seq)
    return by_q


def _is_resolved(ledger: Ledger, stream: list[ForecastRecord]) -> bool:
    """A question is resolved if any of its stream points has a resolution."""
    return any(ledger.resolution_for(r.id) is not None for r in stream)


def _load_spec(questions_dir: Path, qid: str) -> QuestionSpec | None:
    path = Path(questions_dir) / f"{qid}.json"
    if not path.exists():
        return None
    return QuestionSpec.model_validate_json(path.read_text(encoding="utf-8"))


def due_forecasts(
    ledger: Ledger, questions_dir: Path, now: datetime
) -> list[str]:
    """Forecast ids that are unresolved and past their resolution deadline.

    One id per due question — the latest stream point, i.e. the currently
    active forecast that resolution should attach to. Questions with no spec on
    disk are skipped (there is no deadline to compare against). The result is
    sorted for determinism.
    """
    due: list[str] = []
    for qid, stream in _streams_by_question(ledger).items():
        if _is_resolved(ledger, stream):
            continue
        spec = _load_spec(questions_dir, qid)
        if spec is None:
            continue
        if spec.resolution_deadline <= now:
            due.append(stream[-1].id)
    return sorted(due)


def due_triggers(
    ledger: Ledger, now: datetime
) -> list[tuple[str, UpdateTrigger]]:
    """(forecast_id, trigger) pairs whose ``due`` moment has arrived (§5.14).

    Only the latest stream point of each *unresolved* question is considered —
    an earlier point's triggers are stale once it has been superseded. Triggers
    with ``due is None`` are never surfaced (an unscheduled trigger is not
    "due" until a concrete moment is attached). Sorted by forecast id.
    """
    out: list[tuple[str, UpdateTrigger]] = []
    for _qid, stream in sorted(_streams_by_question(ledger).items()):
        if _is_resolved(ledger, stream):
            continue
        latest = stream[-1]
        for trig in latest.update_triggers:
            if trig.due is not None and trig.due <= now:
                out.append((latest.id, trig))
    return out


# --------------------------------------------------------------------------- #
# baseline reading
# --------------------------------------------------------------------------- #
def _coerce_probability(payload: object) -> float | None:
    """Pull a probability out of a baseline JSON payload (float or dict)."""
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in ("probability", "p", "value", "price"):
            if key in payload:
                return float(payload[key])
    return None


def _read_baselines(root: Path, question_id: str) -> dict[str, float]:
    """Recorded baselines for a question: ``{name: probability}``.

    Prefers :func:`oracle.benchmarks.get_baselines`; when that module is not
    yet present (parallel build) it reads the documented store directly at
    ``data/benchmarks/<question_id>/<name>.json``.
    """
    try:
        from oracle.benchmarks import get_baselines
    except ImportError:
        return _read_baselines_from_disk(root, question_id)
    return get_baselines(root, question_id)


def _read_baselines_from_disk(root: Path, question_id: str) -> dict[str, float]:
    directory = Path(root) / "data" / "benchmarks" / question_id
    if not directory.is_dir():
        return {}
    out: dict[str, float] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        prob = _coerce_probability(payload)
        if prob is not None:
            out[path.stem] = prob
    return out


# --------------------------------------------------------------------------- #
# resolution record builder
# --------------------------------------------------------------------------- #
def _score_point(p: float, outcome_int: int) -> dict[str, float]:
    """Single-point score bundle: brier, stream_brier (== brier), log."""
    b = brier(p, outcome_int)
    return {"brier": b, "stream_brier": b, "log": log_score(p, outcome_int)}


def build_resolution(
    ledger: Ledger,
    root: Path,
    fid: str,
    outcome: str,
    evidence: str,
    now: datetime,
    kelly_fraction: float = 0.25,
) -> ResolutionRecord:
    """Build the :class:`ResolutionRecord` for forecast ``fid`` (§5.11, §7.3).

    Computes ``{brier, stream_brier, log}`` for the system (brier/log on the
    latest stream point, stream_brier time-averaged over the whole stream) and
    the same bundle for every recorded baseline (each a single held-constant
    point, so its stream_brier equals its brier). A paper-trade P&L against the
    ``market`` baseline is attached when one exists. VOID outcomes carry no
    scores and instead reference a spec-defect audit note (§5.12), and never
    trade. The returned record is *not* appended — the CLI owns the write.
    """
    forecast = ledger.get_forecast(fid)
    qid = forecast.question_id
    stream = ledger.stream(qid)
    final = max(stream, key=lambda r: r.stream_seq)

    if outcome == "void":
        return ResolutionRecord(
            forecast_id=fid,
            question_id=qid,
            outcome="void",
            resolved_at=now,
            resolution_evidence=evidence,
            scores={},
            baseline_scores={},
            pnl=None,
            spec_defect_audit=f"knowledge/audits/{fid}.md",
        )

    if outcome not in _OUTCOME_INT:
        raise ValueError(
            f"outcome must be 'yes', 'no', or 'void', got {outcome!r}"
        )
    outcome_int = _OUTCOME_INT[outcome]

    points = [(r.committed_at, r.probability) for r in stream]
    scores = {
        "brier": brier(final.probability, outcome_int),
        "stream_brier": stream_brier(points, now, outcome_int),
        "log": log_score(final.probability, outcome_int),
    }

    baselines = _read_baselines(root, qid)
    baseline_scores = {
        name: _score_point(p, outcome_int) for name, p in baselines.items()
    }

    pnl = None
    if _MARKET_BASELINE in baselines:
        pnl = paper_trade(
            final.probability,
            baselines[_MARKET_BASELINE],
            outcome_int,
            kelly_fraction=kelly_fraction,
        )

    return ResolutionRecord(
        forecast_id=fid,
        question_id=qid,
        outcome=outcome,  # type: ignore[arg-type]
        resolved_at=now,
        resolution_evidence=evidence,
        scores=scores,
        baseline_scores=baseline_scores,
        pnl=pnl,
        spec_defect_audit=None,
    )
