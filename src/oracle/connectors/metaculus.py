"""Metaculus connector (free API).

API docs: https://www.metaculus.com/api2/
Endpoints used:
  GET /api2/questions/?search=...        -> {"results": [question, ...]}
  GET /api2/questions/{id}/              -> question

The community prediction is read only into a SealedSnapshot (never into a
BlindCandidate). Parsing is pure so tests exercise it offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from dateutil import parser as dtparser

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://www.metaculus.com/api2"
SITE_URL = "https://www.metaculus.com"
_TIMEOUT = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _url(question: dict) -> str:
    page = question.get("page_url") or f"/questions/{question['id']}/"
    if page.startswith("http"):
        return page
    return f"{SITE_URL}{page}"


def _community_price(question: dict) -> float | None:
    cp = question.get("community_prediction")
    if not cp:
        return None
    full = cp.get("full") if isinstance(cp, dict) else None
    if isinstance(full, dict) and full.get("q2") is not None:
        return float(full["q2"])
    if isinstance(cp, (int, float)):
        return float(cp)
    return None


def _category(question: dict) -> str:
    cats = question.get("categories") or []
    if cats and isinstance(cats[0], dict):
        return cats[0].get("short_name", "other")
    return "other"


def _parse_market_match(question: dict) -> MarketMatch:
    return MarketMatch(
        platform="metaculus",
        market_id=str(question["id"]),
        title=question["title"],
        url=_url(question),
    )


def _parse_list(data: dict) -> list[MarketMatch]:
    return [_parse_market_match(q) for q in data.get("results", [])]


def _parse_price_point(question: dict, ts: datetime | None = None) -> PricePoint:
    price = _community_price(question)
    if price is None:
        raise ValueError(f"no community prediction for metaculus question {question.get('id')}")
    return PricePoint(
        platform="metaculus",
        market_id=str(question["id"]),
        price=price,
        ts=ts or _now(),
    )


def _parse_candidate(question: dict) -> BlindCandidate:
    return BlindCandidate(
        platform="metaculus",
        market_id=str(question["id"]),
        title=question["title"],
        resolution_criteria=question.get("resolution_criteria", ""),
        close_date=dtparser.isoparse(question["close_time"]),
        category=_category(question),
    )


def _parse_snapshot(question: dict, ts: datetime | None = None) -> SealedSnapshot:
    price = _community_price(question)
    return SealedSnapshot(
        platform="metaculus",
        market_id=str(question["id"]),
        price=float(price) if price is not None else 0.0,
        n_forecasters=int(question.get("number_of_forecasters", 0)),
        liquidity=None,
        ts=ts or _now(),
    )


class MetaculusConnector:
    name = "metaculus"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def available(self) -> bool:
        return True

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def search_markets(self, text: str) -> list[MarketMatch]:
        return _parse_list(self._get("/questions/", {"search": text}))

    def get_price(self, market_id: str) -> PricePoint:
        return _parse_price_point(self._get(f"/questions/{market_id}/"))

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        limit = int(filters.get("max", 20))
        data = self._get(
            "/questions/",
            {"status": "open", "type": "binary", "limit": limit,
             "order_by": "close_time"},
        )
        cutoff = _now().timestamp() + closes_within_days * 86_400
        min_forecasters = int(filters.get("min_forecasters", 20))
        out: list[BlindCandidate] = []
        for q in data.get("results", []):
            if int(q.get("number_of_forecasters", 0)) < min_forecasters:
                continue
            close = q.get("close_time")
            if not close or dtparser.isoparse(close).timestamp() > cutoff:
                continue
            out.append(_parse_candidate(q))
        return out

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        return _parse_snapshot(self._get(f"/questions/{market_id}/"))
