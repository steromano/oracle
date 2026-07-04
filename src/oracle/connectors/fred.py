"""FRED connector (free, requires an API key).

API docs: https://fred.stlouisfed.org/docs/api/fred/
Endpoint used:
  GET /fred/series/observations?series_id=...&api_key=...&file_type=json
    -> {"observations": [{"date": "YYYY-MM-DD", "value": "3.2"}, ...]}

FRED is a macro/finance *data* source, not a prediction market, so the
market-shaped Connector methods raise ``NotImplementedError``; its real
capability is ``get_series``. Missing values are encoded by FRED as ``"."`` and
are skipped. Degrades gracefully: ``available()`` is False (never raises) when
``FRED_API_KEY`` is absent.
"""

from __future__ import annotations

import os
from datetime import date, datetime

import httpx
from dateutil import parser as dtparser

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

BASE_URL = "https://api.stlouisfed.org/fred"
_TIMEOUT = 20.0


def _parse_observations(data: dict) -> list[tuple[date, float]]:
    """Turn a FRED observations payload into ``[(date, value), ...]``.

    Missing observations (FRED sends ``"."``) are dropped.
    """
    out: list[tuple[date, float]] = []
    for obs in data.get("observations", []):
        raw = obs.get("value")
        if raw in (None, ".", ""):
            continue
        out.append((dtparser.isoparse(obs["date"]).date(), float(raw)))
    return out


class FredConnector:
    name = "fred"

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url

    def available(self) -> bool:
        return bool(os.getenv("FRED_API_KEY"))

    def get_series(
        self,
        series_id: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> list[tuple[date, float]]:
        """Fetch an observation series as a pandas-free ``[(date, value)]``."""
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            raise RuntimeError("FRED_API_KEY not set")
        params: dict[str, str] = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
        }
        if start is not None:
            params["observation_start"] = _as_iso(start)
        if end is not None:
            params["observation_end"] = _as_iso(end)
        resp = httpx.get(
            f"{self.base_url}/series/observations", params=params, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        return _parse_observations(resp.json())

    # --- Market-shaped protocol methods: not applicable to a data source. --- #
    def search_markets(self, text: str) -> list[MarketMatch]:
        raise NotImplementedError("FRED is a data source, not a market platform")

    def get_price(self, market_id: str) -> PricePoint:
        raise NotImplementedError("FRED is a data source, not a market platform")

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        raise NotImplementedError("FRED is a data source, not a market platform")

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        raise NotImplementedError("FRED is a data source, not a market platform")


def _as_iso(value: str | date | datetime) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return value
