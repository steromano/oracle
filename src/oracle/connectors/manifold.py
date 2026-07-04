"""Manifold Markets connector (free, no auth for reads).

API docs: https://docs.manifold.markets/api
Endpoints used:
  GET /v0/search-markets?term=...        -> list[market]
  GET /v0/market/{id}                    -> market

Parsing is pure (``_parse_*``); network methods are thin wrappers so tests can
exercise the parsers offline against recorded fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://api.manifold.markets/v0"
_TIMEOUT = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _close_date(market: dict) -> datetime:
    # Manifold `closeTime` is epoch milliseconds.
    return datetime.fromtimestamp(market["closeTime"] / 1000, tz=timezone.utc)


def _category(market: dict) -> str:
    slugs = market.get("groupSlugs") or []
    return slugs[0] if slugs else "other"


def _parse_market_match(market: dict) -> MarketMatch:
    return MarketMatch(
        platform="manifold",
        market_id=market["id"],
        title=market["question"],
        url=market["url"],
    )


def _parse_search(data: list[dict]) -> list[MarketMatch]:
    return [_parse_market_match(m) for m in data]


def _parse_price_point(market: dict, ts: datetime | None = None) -> PricePoint:
    return PricePoint(
        platform="manifold",
        market_id=market["id"],
        price=float(market["probability"]),
        ts=ts or _now(),
    )


def _parse_candidate(market: dict) -> BlindCandidate:
    return BlindCandidate(
        platform="manifold",
        market_id=market["id"],
        title=market["question"],
        resolution_criteria=market.get("textDescription", ""),
        close_date=_close_date(market),
        category=_category(market),
    )


def _parse_snapshot(market: dict, ts: datetime | None = None) -> SealedSnapshot:
    return SealedSnapshot(
        platform="manifold",
        market_id=market["id"],
        price=float(market["probability"]),
        n_forecasters=int(market.get("uniqueBettorCount", 0)),
        liquidity=(
            float(market["totalLiquidity"])
            if market.get("totalLiquidity") is not None
            else None
        ),
        ts=ts or _now(),
    )


class ManifoldConnector:
    name = "manifold"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def available(self) -> bool:
        # Reads require no authentication.
        return True

    def _get(self, path: str, params: dict | None = None) -> object:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_markets(self, text: str) -> list[MarketMatch]:
        data = self._get("/search-markets", {"term": text})
        return _parse_search(data)

    def get_price(self, market_id: str) -> PricePoint:
        return _parse_price_point(self._get(f"/market/{market_id}"))

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        limit = int(filters.get("max", 20))
        data = self._get(
            "/search-markets",
            {"term": filters.get("term", ""), "filter": "open", "limit": limit},
        )
        cutoff = _now().timestamp() * 1000 + closes_within_days * 86_400_000
        min_traders = int(filters.get("min_traders", 30))
        out: list[BlindCandidate] = []
        for m in data:
            if m.get("outcomeType") != "BINARY":
                continue
            if int(m.get("uniqueBettorCount", 0)) < min_traders:
                continue
            close = m.get("closeTime")
            if close is None or close > cutoff:
                continue
            out.append(_parse_candidate(m))
        return out

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        return _parse_snapshot(self._get(f"/market/{market_id}"))
