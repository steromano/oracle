"""Baseline store and paired system-vs-baseline comparison (§6.5, §9.2-9.4).

Every question carries a small set of *baseline* forecasts — single-point
predictions that Oracle's harness is measured against (§9.2):

- ``naive-claude`` — clean Claude answering the same QuestionSpec, no harness.
- ``always-0.5`` — the ignorance forecast; auto-derivable, never needs storing.
- ``base-rate-only`` — the outside-view anchor before any inside view.
- ``market`` — market/community price at commit (sealed price for blind imports).

Baselines live one JSON file per name under ``data/benchmarks/<question_id>/``.
``compare`` pairs, question by question, the system's *time-averaged* stream
Brier (§2.3 — each probability active from commit until superseded/resolution)
against the baseline's constant single-point Brier, then ships a bootstrap CI
and win rate. Baselines are held constant by design: naive-claude is a single
point — that constancy is the whole point of the comparison (§6.2). The pairing
is per resolved, non-void question; ``n`` is returned so callers can enforce the
N<30 honesty rule (§9.4).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from oracle.ledger import Ledger
from oracle.models import ForecastRecord, ResolutionRecord
from oracle.scoring import bootstrap_ci, brier, stream_brier

# The ignorance forecast is always available without being recorded (§9.2).
_ALWAYS_HALF = "always-0.5"


def _baseline_dir(root: Path, question_id: str) -> Path:
    return Path(root) / "data" / "benchmarks" / question_id


def record_baseline(root: Path, question_id: str, name: str, p: float) -> Path:
    """Store baseline ``name`` for ``question_id`` at probability ``p``.

    Writes ``data/benchmarks/<question_id>/<name>.json``. Unlike the ledger,
    baselines are not append-only records — re-recording (e.g. the CLI copying
    the sealed market price at commit) simply overwrites the value.
    """
    d = _baseline_dir(root, question_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.json"
    payload = {"question_id": question_id, "name": name, "p": float(p)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def get_baselines(root: Path, question_id: str) -> dict[str, float]:
    """All baseline probabilities for a question, keyed by name.

    ``always-0.5`` is always present (auto-derived) even when nothing has been
    recorded for the question; any recorded ``always-0.5`` file overrides it.
    """
    out: dict[str, float] = {_ALWAYS_HALF: 0.5}
    d = _baseline_dir(root, question_id)
    if d.is_dir():
        for path in sorted(d.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            out[data["name"]] = float(data["p"])
    return out


class Comparison(BaseModel):
    """Paired system-vs-baseline result over resolved questions (§9.4).

    ``mean_delta_brier`` is the mean of per-question
    ``stream_brier(system) - brier(baseline)`` — negative means the system beat
    the baseline (lower Brier is better). ``ci_lo``/``ci_hi`` bound that mean via
    a percentile bootstrap; ``win_rate`` is the fraction of questions where the
    system's Brier was strictly lower. ``n`` is the paired sample size so the
    caller can print ``insufficient N`` when ``n < 30``.
    """

    baseline: str
    n: int
    mean_delta_brier: float
    ci_lo: float
    ci_hi: float
    win_rate: float


def _resolved_questions(
    ledger: Ledger,
) -> list[tuple[str, list[ForecastRecord], ResolutionRecord]]:
    """Resolved questions as ``(question_id, seq-ordered stream, resolution)``.

    A question is resolved when any forecast in its stream has a resolution
    sidecar; there is at most one per stream, so we take whichever we find.
    """
    by_q: dict[str, list[ForecastRecord]] = {}
    for rec in ledger.all_forecasts():
        by_q.setdefault(rec.question_id, []).append(rec)

    out: list[tuple[str, list[ForecastRecord], ResolutionRecord]] = []
    for qid, recs in by_q.items():
        stream = sorted(recs, key=lambda r: r.stream_seq)
        resolution: ResolutionRecord | None = None
        for rec in stream:
            found = ledger.resolution_for(rec.id)
            if found is not None:
                resolution = found
        if resolution is not None:
            out.append((qid, stream, resolution))
    return out


def _matches_segment(stream: list[ForecastRecord], segment: str) -> bool:
    """Whether a stream belongs to ``segment``.

    Segments are matched against the latest forecast's own fields that are
    available without the QuestionSpec: effort tier, resilience grade, and
    experiment variant (§9.4 segment cuts). Richer spec-based segmentation
    (domain, horizon bucket, question type) lives in the report layer.
    """
    latest = stream[-1]
    return segment in (latest.effort_tier, latest.resilience, latest.variant)


def compare(
    ledger: Ledger,
    root: Path,
    baseline: str,
    segment: str | None = None,
) -> Comparison:
    """Paired comparison of the system against ``baseline`` over resolved questions.

    For each resolved, non-void question that has ``baseline`` available, computes
    ``stream_brier(system) - brier(baseline, outcome)`` (the baseline is a single
    point held constant, so its stream Brier equals its point Brier). Returns the
    mean delta, a bootstrap CI on that mean, the win rate, and ``n`` (§9.4).
    """
    deltas: list[float] = []
    wins = 0
    for qid, stream, resolution in _resolved_questions(ledger):
        if resolution.outcome == "void":
            continue
        if segment is not None and not _matches_segment(stream, segment):
            continue
        baselines = get_baselines(root, qid)
        if baseline not in baselines:
            continue

        outcome = 1 if resolution.outcome == "yes" else 0
        points = [(rec.committed_at, rec.probability) for rec in stream]
        sys_sb = stream_brier(points, resolution.resolved_at, outcome)
        base_sb = brier(baselines[baseline], outcome)

        deltas.append(sys_sb - base_sb)
        if sys_sb < base_sb:
            wins += 1

    n = len(deltas)
    if n == 0:
        return Comparison(
            baseline=baseline,
            n=0,
            mean_delta_brier=0.0,
            ci_lo=0.0,
            ci_hi=0.0,
            win_rate=0.0,
        )

    mean_delta = sum(deltas) / n
    lo, hi = bootstrap_ci(deltas)
    return Comparison(
        baseline=baseline,
        n=n,
        mean_delta_brier=mean_delta,
        ci_lo=lo,
        ci_hi=hi,
        win_rate=wins / n,
    )
