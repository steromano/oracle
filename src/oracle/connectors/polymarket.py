"""Polymarket connector (free public gamma API).

API docs: https://docs.polymarket.com/ (gamma-api)
Endpoints used:
  GET /markets?...          -> [market, ...]
  GET /markets/{id}         -> market

Polymarket encodes ``outcomes`` and ``outcomePrices`` as JSON-*strings* (the YES
price is the first element). It has no forecaster count, so
``SealedSnapshot.n_forecasters`` is 0. Parsing is pure.

Import curation (``fetch_candidates``) deliberately returns a *representative,
substantive* sample, not the raw firehose: Polymarket's soonest-closing markets
are dominated by 5-minute "up or down" crypto-tick markets and by large
event-ladders (e.g. one "Will <team> win the World Cup?" market per team). We
order by traded volume, require a real horizon + liquidity + volume, drop tick
markets, and keep at most one market per *event* so a single ladder can't flood
the sample.

Resolution (``get_resolution``) reads Polymarket's settled outcome: a resolved
market has ``closed=true`` with ``outcomePrices`` ["1","0"] (YES) or ["0","1"]
(NO); anything closed-but-ambiguous is treated as VOID.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import httpx
from dateutil import parser as dtparser

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://gamma-api.polymarket.com"
SITE_URL = "https://polymarket.com"
_TIMEOUT = 20.0

# Curation defaults (overridable via the filters dict).
_MIN_LIQUIDITY = 20_000.0
_MIN_VOLUME = 100_000.0
_MIN_CLOSE_DAYS = 2        # exclude sub-day "up or down" tick markets
_FETCH_LIMIT = 250        # scan this many (volume-ordered) before curating down
_TICK_RE = re.compile(r"up or down|next hour|in \d+ minutes", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _outcomes(market: dict) -> list[str]:
    raw = market.get("outcomes")
    vals = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return [str(o).lower() for o in vals]


def _prices(market: dict) -> list[float]:
    raw = market.get("outcomePrices")
    vals = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return [float(p) for p in vals]


def _yes_price(market: dict) -> float:
    prices = _prices(market)
    if not prices:
        raise ValueError(f"no outcomePrices for polymarket market {market.get('id')}")
    return prices[0]


def _is_binary(market: dict) -> bool:
    return _outcomes(market) == ["yes", "no"]


def _event_key(market: dict) -> str:
    """A stable key for the market's parent event, for de-duping ladders/sets."""
    events = market.get("events") or []
    if events and isinstance(events[0], dict) and events[0].get("slug"):
        return f"event:{events[0]['slug']}"
    return f"market:{market.get('id')}"


def _resolution(market: dict) -> str | None:
    """Settled outcome, or None if the market is not resolved yet."""
    if not market.get("closed"):
        return None
    prices = _prices(market)
    if len(prices) >= 2:
        if prices[0] >= 0.99:
            return "yes"
        if prices[0] <= 0.01:
            return "no"
    # Closed but ambiguous / canceled / 50-50 -> VOID (carries no score).
    return "void"


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
    liq = market.get("liquidityNum", market.get("liquidity"))
    return SealedSnapshot(
        platform="polymarket",
        market_id=str(market["id"]),
        price=_yes_price(market),
        n_forecasters=0,
        liquidity=float(liq) if liq is not None else None,
        ts=ts or _now(),
    )


def _curate(markets: list[dict], now_ts: float, floor_ts: float, cutoff_ts: float,
            min_liq: float, min_vol: float, want: int) -> list[BlindCandidate]:
    """Pure curation over a (volume-ordered) market list. Testable offline."""
    out: list[BlindCandidate] = []
    seen_events: set[str] = set()
    for m in markets:
        end = m.get("endDate")
        if not end:
            continue
        ts = dtparser.isoparse(end).timestamp()
        if ts < floor_ts or ts > cutoff_ts:      # too-soon (tick) or too-far
            continue
        if not _is_binary(m):
            continue
        if _TICK_RE.search(m.get("question", "")):
            continue
        if float(m.get("liquidityNum") or 0) < min_liq:
            continue
        if float(m.get("volumeNum") or 0) < min_vol:
            continue
        ek = _event_key(m)
        if ek in seen_events:                     # one market per event (dedup ladders)
            continue
        seen_events.add(ek)
        out.append(_parse_candidate(m))
        if len(out) >= want:
            break
    return out


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
        want = int(filters.get("max", 20))
        min_liq = float(filters.get("min_liquidity", _MIN_LIQUIDITY))
        min_vol = float(filters.get("min_volume", _MIN_VOLUME))
        min_days = int(filters.get("min_close_days", _MIN_CLOSE_DAYS))
        now = _now()
        now_ts = now.timestamp()
        data = self._get(
            "/markets",
            {"active": "true", "closed": "false", "order": "volumeNum",
             "ascending": "false",
             "end_date_min": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "limit": _FETCH_LIMIT},
        )
        return _curate(
            data if isinstance(data, list) else [],
            now_ts=now_ts,
            floor_ts=now_ts + min_days * 86_400,
            cutoff_ts=now_ts + closes_within_days * 86_400,
            min_liq=min_liq, min_vol=min_vol, want=want,
        )

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        return _parse_snapshot(self._get(f"/markets/{market_id}"))

    def get_resolution(self, market_id: str) -> str | None:
        """Return 'yes'/'no'/'void' if Polymarket has settled the market, else None."""
        return _resolution(self._get(f"/markets/{market_id}"))
