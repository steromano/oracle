"""Tests for the blind import machinery (Task 10, §5.13 / §6.6)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle import importer
from oracle.connectors import BlindCandidate, SealedSnapshot
from oracle.models import QuestionSpec

UTC = timezone.utc
NOW = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)


# -- fixtures / builders ------------------------------------------------------


def _candidate(
    *,
    platform: str = "manifold",
    market_id: str = "m-001",
    title: str = "Will the RBA cut the cash rate in August 2026?",
    category: str = "macro",
    close_date: datetime | None = None,
) -> BlindCandidate:
    return BlindCandidate(
        platform=platform,
        market_id=market_id,
        title=title,
        resolution_criteria="Resolves YES if the post-meeting statement announces a cut.",
        close_date=close_date or datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        category=category,
    )


def _snapshot(
    *, platform: str = "manifold", market_id: str = "m-001", price: float = 0.58
) -> SealedSnapshot:
    return SealedSnapshot(
        platform=platform,
        market_id=market_id,
        price=price,
        n_forecasters=120,
        liquidity=500.0,
        ts=NOW,
    )


class _FakeConnector:
    """Offline stand-in for a platform connector.

    ``fetch_candidates`` honours the ``min_traders`` filter so the pass-through
    of quality thresholds to the connector layer is genuinely exercised.
    """

    def __init__(self, name: str, candidates: list[tuple[BlindCandidate, int]]):
        self.name = name
        self._candidates = candidates
        self._available = True

    def available(self) -> bool:
        return self._available

    def fetch_candidates(self, closes_within_days: int, filters: dict) -> list[BlindCandidate]:
        min_t = filters.get("min_traders", 0)
        return [c for (c, traders) in self._candidates if traders >= min_t]

    # unused by importer paths under test
    def search_markets(self, text):  # pragma: no cover
        return []

    def get_price(self, market_id):  # pragma: no cover
        raise NotImplementedError

    def fetch_snapshot(self, market_id):  # pragma: no cover
        raise NotImplementedError


def _patch_registry(monkeypatch, conns: dict) -> None:
    monkeypatch.setattr(importer, "registry", lambda: conns)


def _write_existing_question(questions_dir: Path, *, qid: str, platform: str, market_id: str) -> None:
    spec = candidate_spec = importer.candidate_to_spec(
        _candidate(platform=platform, market_id=market_id), NOW, 1
    )
    # override the id to the requested value for clarity
    data = candidate_spec.model_copy(update={"id": qid})
    (questions_dir / f"{qid}.json").write_text(data.model_dump_json(indent=2), encoding="utf-8")


# -- fetch_and_filter ---------------------------------------------------------


def test_fetch_and_filter_drops_below_threshold(monkeypatch, state_root: Path):
    good = _candidate(market_id="m-good")
    weak = _candidate(market_id="m-weak", title="joke market")
    _patch_registry(
        monkeypatch,
        {"manifold": _FakeConnector("manifold", [(good, 50), (weak, 5)])},
    )
    out = importer.fetch_and_filter(
        14, ["manifold"], {"min_traders": 30}, state_root / "data" / "questions"
    )
    ids = [c.market_id for c in out]
    assert ids == ["m-good"]


def test_fetch_and_filter_excludes_categories(monkeypatch, state_root: Path):
    macro = _candidate(market_id="m-macro", category="macro")
    sport = _candidate(market_id="m-sport", category="sports")
    _patch_registry(
        monkeypatch,
        {"manifold": _FakeConnector("manifold", [(macro, 99), (sport, 99)])},
    )
    out = importer.fetch_and_filter(
        14, ["manifold"], {"exclude_categories": ["sports"]}, state_root / "data" / "questions"
    )
    assert [c.market_id for c in out] == ["m-macro"]


def test_fetch_and_filter_dedupes_against_existing(monkeypatch, state_root: Path):
    qdir = state_root / "data" / "questions"
    _write_existing_question(qdir, qid="Q-20260701-001", platform="manifold", market_id="m-dup")
    dup = _candidate(market_id="m-dup")
    fresh = _candidate(market_id="m-fresh")
    _patch_registry(
        monkeypatch,
        {"manifold": _FakeConnector("manifold", [(dup, 99), (fresh, 99)])},
    )
    out = importer.fetch_and_filter(14, ["manifold"], {}, qdir)
    assert [c.market_id for c in out] == ["m-fresh"]


def test_fetch_and_filter_dedupes_within_batch(monkeypatch, state_root: Path):
    a = _candidate(market_id="m-x")
    dup = _candidate(market_id="m-x", title="same market again")
    _patch_registry(
        monkeypatch,
        {"manifold": _FakeConnector("manifold", [(a, 99), (dup, 99)])},
    )
    out = importer.fetch_and_filter(14, ["manifold"], {}, state_root / "data" / "questions")
    assert [c.market_id for c in out] == ["m-x"]


def test_fetch_and_filter_skips_unavailable_or_unknown_platform(monkeypatch, state_root: Path):
    conn = _FakeConnector("manifold", [(_candidate(market_id="m-1"), 99)])
    conn._available = False
    _patch_registry(monkeypatch, {"manifold": conn})
    # unavailable manifold + a platform not in the registry at all
    out = importer.fetch_and_filter(
        14, ["manifold", "metaculus"], {}, state_root / "data" / "questions"
    )
    assert out == []


# -- candidate_to_spec --------------------------------------------------------


def test_candidate_to_spec_sets_blind_import_and_sealed_path():
    c = _candidate()
    spec = importer.candidate_to_spec(c, NOW, 3)
    assert isinstance(spec, QuestionSpec)
    assert spec.id == "Q-20260705-003"
    assert spec.origin == "import"
    assert spec.blind is True
    assert spec.q_type == "binary"
    assert spec.sealed_snapshot is not None
    assert spec.sealed_snapshot.startswith("data/sealed/")
    # horizon = (2026-08-12 - 2026-07-05) = 38 days
    assert spec.horizon_days == 38
    assert spec.resolution_criteria == c.resolution_criteria
    assert spec.resolution_deadline == c.close_date


def test_candidate_to_spec_carries_no_price():
    c = _candidate()
    # the blind type itself has no market opinion fields
    assert not hasattr(c, "price")
    spec = importer.candidate_to_spec(c, NOW, 1)
    dumped = spec.model_dump()
    assert "price" not in dumped
    # a linked market is recorded, but never with a price when blind
    assert len(spec.linked_markets) == 1
    assert spec.linked_markets[0].price_at_creation is None
    assert '"price"' not in spec.model_dump_json()


# -- seal / unseal ------------------------------------------------------------


def test_seal_and_unseal_roundtrip(state_root: Path):
    c = _candidate()
    spec = importer.candidate_to_spec(c, NOW, 1)
    # persist the spec so unseal can map question_id -> sealed pointer
    (state_root / "data" / "questions" / f"{spec.id}.json").write_text(
        spec.model_dump_json(indent=2), encoding="utf-8"
    )
    snap = _snapshot(price=0.58)
    path = importer.seal(state_root, c, snap)
    assert path.exists()
    # the sealed file must live under data/sealed and match the spec pointer
    assert path == state_root / spec.sealed_snapshot
    assert importer.unseal_market_baseline(state_root, spec.id) == pytest.approx(0.58)


def test_seal_refuses_overwrite(state_root: Path):
    c = _candidate()
    importer.seal(state_root, c, _snapshot())
    with pytest.raises(FileExistsError):
        importer.seal(state_root, c, _snapshot())


def test_unseal_missing_spec_raises(state_root: Path):
    with pytest.raises(FileNotFoundError):
        importer.unseal_market_baseline(state_root, "Q-20260705-999")
