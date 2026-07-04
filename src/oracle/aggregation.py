"""Probability pooling / aggregation (spec §6.4).

Pure functions only — no I/O, no dependency on the ledger. Every pooler takes a
list of probabilities in [0, 1] and returns a single pooled probability in the
same range. ``pool`` is the dispatcher used by the CLI's ``oracle aggregate``.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

# Clip bound used only inside odds-space math so that p == 0 or p == 1 do not
# produce 0 or infinite odds.
_ODDS_EPS = 1e-6

PoolMethod = Literal["median", "trimmed", "geo_odds"]


def pool_median(ps: list[float]) -> float:
    """Median of the probabilities (the default pool, per §5.7)."""
    if not ps:
        raise ValueError("pool_median requires at least one probability")
    return float(np.median(np.asarray(ps, dtype=float)))


def pool_trimmed_mean(ps: list[float], trim: float = 0.2) -> float:
    """Symmetric trimmed mean: drop ``trim`` fraction from each tail, then mean.

    The number trimmed from each end is ``floor(trim * n)``; for small n this is
    zero, so the trimmed mean gracefully reduces to the ordinary mean.
    """
    if not ps:
        raise ValueError("pool_trimmed_mean requires at least one probability")
    if not 0.0 <= trim < 0.5:
        raise ValueError("trim must be in [0, 0.5)")
    arr = np.sort(np.asarray(ps, dtype=float))
    n = arr.size
    k = int(np.floor(trim * n))
    if 2 * k >= n:
        # Trimming would remove everything; fall back to the full mean.
        k = 0
    kept = arr[k : n - k] if k else arr
    return float(np.mean(kept))


def pool_geo_mean_odds(ps: list[float]) -> float:
    """Geometric mean in odds space, mapped back to probability.

    ``o = p / (1 - p)``; ``g = exp(mean(log(o)))``; return ``g / (1 + g)``.
    Inputs are clipped to ``[1e-6, 1 - 1e-6]`` first so 0/1 stay finite.
    """
    if not ps:
        raise ValueError("pool_geo_mean_odds requires at least one probability")
    p = np.clip(np.asarray(ps, dtype=float), _ODDS_EPS, 1.0 - _ODDS_EPS)
    odds = p / (1.0 - p)
    g = np.exp(np.mean(np.log(odds)))
    return float(g / (1.0 + g))


_POOLERS = {
    "median": pool_median,
    "trimmed": pool_trimmed_mean,
    "geo_odds": pool_geo_mean_odds,
}


def pool(
    ps: list[float],
    method: PoolMethod,
    market_price: float | None = None,
    market_weight: float = 1.0,
) -> float:
    """Pool ``ps`` by ``method``, optionally folding in a market price.

    When ``market_price`` is given it is appended as ``market_weight`` extra
    copies before pooling, so a weight of 1 contributes exactly one additional
    vote (AIA's model+market ensemble, §5.7). ``market_weight`` is interpreted
    as a vote count and rounded to the nearest non-negative integer.
    """
    if method not in _POOLERS:
        raise ValueError(
            f"unknown pool method {method!r}; expected one of {sorted(_POOLERS)}"
        )
    values = list(ps)
    if market_price is not None:
        copies = int(round(market_weight))
        if copies < 0:
            raise ValueError("market_weight must be non-negative")
        values.extend([market_price] * copies)
    return _POOLERS[method](values)
