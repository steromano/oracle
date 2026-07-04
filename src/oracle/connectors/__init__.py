"""Connector registry, capability detection, and shared blind-safe types (§6.6).

Each connector is coded to a platform's documented API shape and tested offline
against recorded fixtures (``tests/fixtures/connectors``). Parsing is split into
pure ``_parse_*(json) -> Model`` functions that the tests call directly; the
network-touching methods are thin wrappers around them.

Blinding is enforced by the type system, not by prompt instructions:
``BlindCandidate`` deliberately has no ``price``/``community``/``comments``
field, so the market's opinion cannot reach the forecasting pipeline. The full
opinion is only ever materialized as a ``SealedSnapshot``, which the CLI writes
to ``data/sealed/`` and only the resolve/commit paths read (§5.13).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..models import UTCModel


class MarketMatch(UTCModel):
    """A candidate market found by a free-text search."""

    platform: str
    market_id: str
    title: str
    url: str


class PricePoint(UTCModel):
    """A single price/probability observation for a market."""

    platform: str
    market_id: str
    price: float
    ts: datetime


class BlindCandidate(UTCModel):
    """A market question STRIPPED of all crowd opinion (§6.6).

    Carries only what the forecasting pipeline is allowed to see in blind mode:
    the question text and its resolution rules. There is intentionally no
    ``price``, ``community``, ``comments``, ``n_forecasters`` or ``liquidity``
    field — the type is the enforcement mechanism.
    """

    platform: str
    market_id: str
    title: str
    resolution_criteria: str
    close_date: datetime
    category: str


class SealedSnapshot(UTCModel):
    """The full market opinion, captured at import time and sealed (§5.13).

    Written to ``data/sealed/`` by the CLI and read only by the resolve/commit
    paths — never surfaced to a forecasting session.
    """

    platform: str
    market_id: str
    price: float
    n_forecasters: int
    liquidity: float | None
    ts: datetime


@runtime_checkable
class Connector(Protocol):
    """Uniform interface every platform connector implements (§6.6)."""

    name: str

    def available(self) -> bool: ...
    def search_markets(self, text: str) -> list[MarketMatch]: ...
    def get_price(self, market_id: str) -> PricePoint: ...
    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]: ...
    def fetch_snapshot(self, market_id: str) -> SealedSnapshot: ...


def registry() -> dict[str, Connector]:
    """All connectors keyed by ``name``."""
    from .asknews import AskNewsConnector
    from .fred import FredConnector
    from .manifold import ManifoldConnector
    from .metaculus import MetaculusConnector
    from .polymarket import PolymarketConnector

    connectors: list[Connector] = [
        ManifoldConnector(),
        MetaculusConnector(),
        PolymarketConnector(),
        FredConnector(),
        AskNewsConnector(),
    ]
    return {c.name: c for c in connectors}


def doctor() -> list[tuple[str, bool, str]]:
    """Report ``(name, available, detail)`` for every connector.

    ``detail`` never contains a secret value — only whether the relevant
    environment variable is present.
    """
    rows: list[tuple[str, bool, str]] = []
    for name, conn in registry().items():
        try:
            available = conn.available()
        except Exception as exc:  # defensive: doctor must never crash a session
            rows.append((name, False, f"error: {type(exc).__name__}"))
            continue
        rows.append((name, available, _detail(name, available)))
    return rows


def _detail(name: str, available: bool) -> str:
    if name in ("manifold", "metaculus", "polymarket"):
        return "no auth required" if available else "unavailable"
    if name == "fred":
        return "FRED_API_KEY set" if os.getenv("FRED_API_KEY") else "FRED_API_KEY not set"
    if name == "asknews":
        has_creds = bool(os.getenv("ASKNEWS_CLIENT_ID") and os.getenv("ASKNEWS_CLIENT_SECRET"))
        if available:
            return "asknews sdk + credentials present"
        if not has_creds:
            return "ASKNEWS_CLIENT_ID/SECRET not set"
        return "asknews sdk not installed"
    return "unavailable"


__all__ = [
    "MarketMatch",
    "PricePoint",
    "BlindCandidate",
    "SealedSnapshot",
    "Connector",
    "registry",
    "doctor",
]
