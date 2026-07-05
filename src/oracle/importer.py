"""Blind import orchestration: fetch → filter → seal → queue → unseal (§5.13).

This module is the glue between the connector layer and the ledger/question
store for the *import* workflow. Its defining constraint is blinding: the crowd's
opinion (price, community forecast, trader count, comments) must never reach the
forecasting pipeline. That is enforced structurally —

* ``fetch_and_filter`` only ever handles :class:`BlindCandidate` objects, which
  carry no market-opinion fields at all (§6.6). Quality thresholds that *do*
  need the opinion (minimum trader / forecaster counts) are pushed down into the
  connector via the ``filters`` dict, so the raw counts never surface here.
* The full opinion is materialised exactly once, as a :class:`SealedSnapshot`
  written by :func:`seal` to ``data/sealed/`` and read back only by the
  CLI-only :func:`unseal_market_baseline` (never by a forecasting session).

``candidate_to_spec`` converts a blind candidate into a :class:`QuestionSpec`
with ``origin="import"`` and ``blind=True``; it records a :class:`MarketLink`
so the question is deduplicable and later unsealable, but with no price.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .connectors import BlindCandidate, SealedSnapshot, registry
from .models import MarketLink, QuestionSpec, new_question_id


def fetch_and_filter(
    closes_within_days: int,
    platforms: list[str],
    filters: dict,
    existing_questions_dir: Path,
) -> list[BlindCandidate]:
    """Fetch soon-closing candidates and apply import quality filters.

    Minimum trader / forecaster thresholds are forwarded to each connector via
    ``filters`` (they need the crowd counts, which are stripped from the blind
    payload). This function then applies the filters that operate on the blind
    payload alone: category excludes, in-batch dedupe, and dedupe against the
    markets already linked by questions in ``existing_questions_dir``.

    Recognised ``filters`` keys: ``min_traders`` / ``min_forecasters`` (passed
    through to connectors) and ``exclude_categories`` (a list of category names,
    matched case-insensitively).
    """
    exclude = {c.lower() for c in filters.get("exclude_categories", [])}
    already = _existing_market_keys(Path(existing_questions_dir))
    conns = registry()

    out: list[BlindCandidate] = []
    seen: set[tuple[str, str]] = set()
    for platform in platforms:
        conn = conns.get(platform)
        if conn is None or not conn.available():
            continue
        try:
            candidates = list(conn.fetch_candidates(closes_within_days, filters))
        except Exception as exc:  # noqa: BLE001 — one bad connector must not abort the batch
            # Graceful degradation (§6.6): a connector that errors at fetch time
            # (e.g. an API returning 403/5xx) is skipped so other platforms still
            # contribute candidates, mirroring the "unavailable connector" path.
            print(
                f"warning: skipping connector '{platform}': "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        for cand in candidates:
            key = (cand.platform, cand.market_id)
            if key in already or key in seen:
                continue
            if cand.category.lower() in exclude:
                continue
            seen.add(key)
            out.append(cand)
    return out


def seal(root: Path, candidate: BlindCandidate, snapshot: SealedSnapshot) -> Path:
    """Write the full market snapshot to ``data/sealed/`` (append-only).

    The file is keyed by the market identity (the only stable id available from
    a :class:`BlindCandidate`), which matches the ``sealed_snapshot`` pointer set
    by :func:`candidate_to_spec`. Refuses to overwrite an existing sealed file so
    the "captured before our forecast" audit guarantee cannot be tampered with.
    """
    path = Path(root) / _sealed_relpath(candidate.platform, candidate.market_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: raises FileExistsError if already sealed.
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(snapshot.model_dump_json(indent=2))
    return path


def candidate_to_spec(c: BlindCandidate, now: datetime, seq: int) -> QuestionSpec:
    """Convert a blind candidate into a blind, import-origin ``QuestionSpec``.

    Adopts the platform's resolution criteria verbatim, records a priceless
    :class:`MarketLink` (blinding), and points ``sealed_snapshot`` at the file
    :func:`seal` will write for this market.
    """
    qid = new_question_id(now, seq)
    horizon_days = (c.close_date - now).days
    return QuestionSpec(
        id=qid,
        title=c.title,
        question_text=c.title,
        q_type="binary",
        thresholds=None,
        resolution_criteria=c.resolution_criteria,
        resolution_source=f"{c.platform} market {c.market_id}",
        resolution_deadline=c.close_date,
        edge_cases="Resolves VOID if the source market voids or is marked N/A.",
        domain=c.category,
        horizon_days=horizon_days,
        linked_markets=[
            MarketLink(platform=c.platform, market_id=c.market_id, price_at_creation=None)
        ],
        origin="import",
        blind=True,
        sealed_snapshot=_sealed_relpath(c.platform, c.market_id),
        created_at=now,
        created_by="import",
    )


def unseal_market_baseline(root: Path, question_id: str) -> float:
    """Read the sealed market price for a question (CLI-only path, §5.13).

    Loads the question spec to find its ``sealed_snapshot`` pointer, then reads
    the sealed :class:`SealedSnapshot` and returns its price. This is the only
    sanctioned reader of ``data/sealed/`` outside of resolution.
    """
    root = Path(root)
    spec_path = root / "data" / "questions" / f"{question_id}.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"no question spec {question_id!r} at {spec_path}")
    spec = QuestionSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    if spec.sealed_snapshot is None:
        raise ValueError(f"question {question_id!r} has no sealed snapshot")
    sealed_path = root / spec.sealed_snapshot
    if not sealed_path.exists():
        raise FileNotFoundError(f"sealed snapshot missing at {sealed_path}")
    snap = SealedSnapshot.model_validate_json(sealed_path.read_text(encoding="utf-8"))
    return snap.price


# -- internals ----------------------------------------------------------------


def _sealed_relpath(platform: str, market_id: str) -> str:
    """Root-relative path of the sealed file for a market identity."""
    safe = f"{platform}-{market_id}".replace("/", "_").replace(" ", "_")
    return f"data/sealed/{safe}.json"


def _existing_market_keys(questions_dir: Path) -> set[tuple[str, str]]:
    """``(platform, market_id)`` for every market linked by an existing spec."""
    keys: set[tuple[str, str]] = set()
    if not questions_dir.exists():
        return keys
    for path in questions_dir.glob("*.json"):
        try:
            spec = QuestionSpec.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            # A malformed / unrelated JSON file must not break import fetching.
            continue
        for link in spec.linked_markets:
            keys.add((link.platform, link.market_id))
    return keys
