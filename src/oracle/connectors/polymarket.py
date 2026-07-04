"""Polymarket connector (free public gamma API).

API docs: https://docs.polymarket.com/ (gamma-api)
Endpoints used:
  GET /markets?...          -> [market, ...]
  GET /markets/{id}         -> market

Polymarket encodes ``outcomes`` and ``outcomePrices`` as JSON-*strings*; the
YES price is the first element. Polymarket has no notion of forecaster count,
so ``SealedSnapshot.n_forecasters`` is 0. Parsing is pure.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from dateutil import parser as dtparser

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://gamma-api.polymarket.com"
SITE_URL = "https://polymarket.com"
_TIMEOUT = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _yes_price(market: dict) -> float:
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        prices = json.loads(raw)
    else:
        prices = raw or []
    if not prices:
        raise ValueError(f"no outcomePrices for polymarket market {market.get('id')}")
    return float(prices[0])


def _url(market: dict) -> str:
    slug = market.get("slug")
    return f"{SITE_URL}/event/{slug}" if slug else f"{SITE_URL}/market/{market['id']}"


def _parse_market_match(market: dict) -> MarketMatch:
    return MarketMatch(
        platform="polymarket",
        market_id=str(market["id"]),
        title=market["question"],
        url=_url(market),
    )


def _parse_list(data: list[dict]) -> list[MarketMatch]:
    return [_parse_market_match(m) for m in data]


def _parse_price_point(market: dict, ts: datetime | None = None) -> PricePoint:
    return PricePoint(
        platform="polymarket",
        market_id=str(market["id"]),
        price=_yes_price(market),
        ts=ts or _now(),
    )


def _parse_candidate(market: dict) -> BlindCandidate:
    return BlindCandidate(
        platform="polymarket",
        market_id=str(market["id"]),
        title=market["question"],
        resolution_criteria=market.get("description", ""),
        close_date=dtparser.isoparse(market["endDate"]),
        category=market.get("category", "other"),
    )


def _parse_snapshot(market: dict, ts: datetime | None = None) -> SealedSnapshot:
    liq = market.get("liquidity")
    return SealedSnapshot(
        platform="polymarket",
        market_id=str(market["id"]),
        price=_yes_price(market),
        n_forecasters=0,
        liquidity=float(liq) if liq is not None else None,
        ts=ts or _now(),
    )


class PolymarketConnector:
    name = "polymarket"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def available(self) -> bool:
        return True

    def _get(self, path: str, params: dict | None = None) -> object:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_markets(self, text: str) -> list[MarketMatch]:
        data = self._get("/markets", {"active": "true", "closed": "false"})
        matches = _parse_list(data)
        needle = text.lower()
        return [m for m in matches if needle in m.title.lower()] or matches

    def get_price(self, market_id: str) -> PricePoint:
        return _parse_price_point(self._get(f"/markets/{market_id}"))

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        limit = int(filters.get("max", 20))
        data = self._get(
            "/markets",
            {"active": "true", "closed": "false", "limit": limit},
        )
        cutoff = _now().timestamp() + closes_within_days * 86_400
        out: list[BlindCandidate] = []
        for m in data:
            end = m.get("endDate")
            if not end or dtparser.isoparse(end).timestamp() > cutoff:
                continue
            out.append(_parse_candidate(m))
        return out

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        return _parse_snapshot(self._get(f"/markets/{market_id}"))
