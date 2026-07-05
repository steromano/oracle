"""Metaculus connector (requires an API token as of 2026).

API docs: https://www.metaculus.com/api/
Endpoints used (all return "post" objects wrapping a nested ``question``):
  GET /api2/questions/?statuses=open&forecast_type=binary  -> {"results": [post, ...]}
  GET /api2/questions/{id}/                                 -> post

Auth: reads now require ``Authorization: Token <METACULUS_API_TOKEN>`` (the old
unauthenticated api2 returns 403). The response schema was also overhauled: each
result is a *post* with id/title/nr_forecasters/projects, and the forecast
``question`` (type, scheduled_close_time, resolution_criteria, recency-weighted
community aggregation) is nested under ``post["question"]``.

The community prediction is read only into a SealedSnapshot (never into a
BlindCandidate). Parsing is pure so tests exercise it offline.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from dateutil import parser as dtparser

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://www.metaculus.com/api2"
SITE_URL = "https://www.metaculus.com"
_TIMEOUT = 20.0
_TOKEN_ENV = "METACULUS_API_TOKEN"
_USER_AGENT = "oracle-forecasting-harness/0.1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Metaculus v2 wraps each question in a "post". A post carries id/title/
# nr_forecasters/projects; the forecast question (type, close time, resolution
# criteria, community aggregation) is nested under post["question"].


def _q(post: dict) -> dict:
    return post.get("question") or {}


def _url(post: dict) -> str:
    page = post.get("url") or f"/questions/{post['id']}/"
    return page if page.startswith("http") else f"{SITE_URL}{page}"


def _close_time(post: dict) -> str | None:
    q = _q(post)
    return q.get("scheduled_close_time") or post.get("scheduled_close_time")


def _community_price(post: dict) -> float | None:
    """Community median for a binary, from the recency-weighted aggregation.

    Empty until Metaculus reveals the CP (``cp_reveal_time``); returns None then.
    """
    rw = (_q(post).get("aggregations") or {}).get("recency_weighted") or {}
    for bucket in (rw.get("latest") or {}, (rw.get("history") or [{}])[-1]):
        if not isinstance(bucket, dict):
            continue
        for key in ("centers", "means"):
            vals = bucket.get(key)
            if isinstance(vals, list) and vals and isinstance(vals[0], (int, float)):
                return float(vals[0])
    return None


def _category(post: dict) -> str:
    cats = (post.get("projects") or {}).get("category") or []
    if cats and isinstance(cats[0], dict):
        return cats[0].get("slug") or cats[0].get("name") or "other"
    return "other"


def _parse_market_match(post: dict) -> MarketMatch:
    return MarketMatch(
        platform="metaculus",
        market_id=str(post["id"]),
        title=post["title"],
        url=_url(post),
    )


def _parse_list(data: dict) -> list[MarketMatch]:
    return [_parse_market_match(p) for p in data.get("results", [])]


def _parse_price_point(post: dict, ts: datetime | None = None) -> PricePoint:
    price = _community_price(post)
    if price is None:
        raise ValueError(f"no community prediction for metaculus post {post.get('id')}")
    return PricePoint(
        platform="metaculus",
        market_id=str(post["id"]),
        price=price,
        ts=ts or _now(),
    )


def _parse_candidate(post: dict) -> BlindCandidate:
    close = _close_time(post)
    return BlindCandidate(
        platform="metaculus",
        market_id=str(post["id"]),
        title=post["title"],
        resolution_criteria=_q(post).get("resolution_criteria", ""),
        close_date=dtparser.isoparse(close),
        category=_category(post),
    )


def _parse_snapshot(post: dict, ts: datetime | None = None) -> SealedSnapshot:
    price = _community_price(post)
    return SealedSnapshot(
        platform="metaculus",
        market_id=str(post["id"]),
        # None (not 0.0) when the community prediction is hidden/unrevealed, so it
        # never becomes a misleading market=0.00 benchmark at unseal time.
        price=float(price) if price is not None else None,
        n_forecasters=int(post.get("nr_forecasters", 0)),
        liquidity=None,
        ts=ts or _now(),
    )


class MetaculusConnector:
    name = "metaculus"

    def __init__(self, base_url: str = BASE_URL, token: str | None = None) -> None:
        self.base_url = base_url
        # Metaculus now requires an auth token even for read endpoints (the old
        # unauthenticated api2 access returns 403). Fall back to the env var so
        # the connector degrades cleanly when no key is configured.
        self.token = token if token is not None else os.environ.get(_TOKEN_ENV)

    def available(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict:
        h = {"User-Agent": _USER_AGENT}
        if self.token:
            h["Authorization"] = f"Token {self.token}"
        return h

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = httpx.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def search_markets(self, text: str) -> list[MarketMatch]:
        return _parse_list(self._get("/questions/", {"search": text}))

    def get_price(self, market_id: str) -> PricePoint:
        return _parse_price_point(self._get(f"/questions/{market_id}/"))

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        want = int(filters.get("max", 20))
        min_forecasters = int(filters.get("min_forecasters", 20))
        now = _now()
        # Ordered by close time ascending, bounded to future closes server-side
        # (``statuses=open`` alone still surfaces legacy past-close questions).
        # No community prediction is requested (with_cp omitted) — candidates are
        # blind by construction. We still re-check the window client-side.
        data = self._get(
            "/questions/",
            {"statuses": "open", "forecast_type": "binary", "limit": 100,
             "order_by": "scheduled_close_time",
             "scheduled_close_time__gt": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
        )
        now_ts = now.timestamp()
        cutoff = now_ts + closes_within_days * 86_400
        out: list[BlindCandidate] = []
        for post in data.get("results", []):
            if int(post.get("nr_forecasters", 0)) < min_forecasters:
                continue
            close = _close_time(post)
            if not close:
                continue
            close_ts = dtparser.isoparse(close).timestamp()
            if close_ts <= now_ts or close_ts > cutoff:
                continue
            out.append(_parse_candidate(post))
            if len(out) >= want:
                break
        return out

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        return _parse_snapshot(self._get(f"/questions/{market_id}/"))
