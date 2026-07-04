"""AskNews connector (optional paid; guarded import).

AskNews provides structured, dated news retrieval built for forecasting bots
(§8.2). The SDK is an *optional* dependency, so the import is guarded: if the
package is not installed, the connector simply reports itself unavailable and
never raises. It is also a news source rather than a prediction market, so the
market-shaped Connector methods raise ``NotImplementedError``.

Credentials: ``ASKNEWS_CLIENT_ID`` + ``ASKNEWS_CLIENT_SECRET``.
"""

from __future__ import annotations

import os

from . import BlindCandidate, MarketMatch, PricePoint, SealedSnapshot

try:  # optional dependency — never a hard requirement
    import asknews_sdk  # type: ignore

    _HAS_SDK = True
except Exception:  # pragma: no cover - depends on install state
    asknews_sdk = None  # type: ignore
    _HAS_SDK = False


class AskNewsConnector:
    name = "asknews"

    def available(self) -> bool:
        has_creds = bool(
            os.getenv("ASKNEWS_CLIENT_ID") and os.getenv("ASKNEWS_CLIENT_SECRET")
        )
        return _HAS_SDK and has_creds

    def search_news(self, query: str, n_articles: int = 10) -> list[dict]:
        """Return dated news articles for ``query`` (empty if unavailable)."""
        if not self.available():
            return []
        client = asknews_sdk.AskNewsSDK(  # type: ignore[attr-defined]
            client_id=os.environ["ASKNEWS_CLIENT_ID"],
            client_secret=os.environ["ASKNEWS_CLIENT_SECRET"],
        )
        response = client.news.search_news(query=query, n_articles=n_articles)
        return [a.model_dump() if hasattr(a, "model_dump") else a for a in response.as_dicts]

    # --- Market-shaped protocol methods: not applicable to a news source. --- #
    def search_markets(self, text: str) -> list[MarketMatch]:
        raise NotImplementedError("AskNews is a news source, not a market platform")

    def get_price(self, market_id: str) -> PricePoint:
        raise NotImplementedError("AskNews is a news source, not a market platform")

    def fetch_candidates(
        self, closes_within_days: int, filters: dict
    ) -> list[BlindCandidate]:
        raise NotImplementedError("AskNews is a news source, not a market platform")

    def fetch_snapshot(self, market_id: str) -> SealedSnapshot:
        raise NotImplementedError("AskNews is a news source, not a market platform")
