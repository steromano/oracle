"""Deterministic scoring math for Oracle (§2.3, §9.4).

Pure functions only — no I/O, no LLM. Every metric here is what the CLI and
report layers call so that a Brier score is never computed "in the model's
head" (§3.1). Conventions:

- Outcomes are ``0`` / ``1`` integers (``yes`` == 1, ``no`` == 0).
- ``brier`` and ``log_score`` are oriented so **lower is better** (0 = perfect).
- All datetimes are tz-aware UTC; interval math uses raw ``timedelta`` seconds.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
from pydantic import BaseModel

# Log-score clipping bound (§2.3) — bounds the penalty for a confident miss.
_LOG_CLIP = 1e-4
# Edge below which paper_trade declines to bet.
_NO_BET_EPS = 1e-6


def brier(p: float, outcome: int) -> float:
    """Brier score for a single forecast: ``(p - outcome) ** 2``.

    ``outcome`` in ``{0, 1}``. Range ``[0, 1]``; 0.25 is the ignorance score of
    a constant 0.5 forecast; lower is better.
    """
    return (p - outcome) ** 2


def stream_brier(
    points: list[tuple[datetime, float]],
    resolved_at: datetime,
    outcome: int,
) -> float:
    """Duration-weighted (time-averaged) Brier over a forecast stream (§2.3).

    Each point's forecast is active from its own timestamp until the next
    point's timestamp, and the final point stays active until ``resolved_at``.
    The result is ``sum(weight_i * brier(p_i, outcome))`` where ``weight_i`` is
    the fraction of the stream's open life that point ``i`` was active. Reduces
    exactly to ``brier`` for a single point.
    """
    if not points:
        raise ValueError("stream_brier requires at least one point")

    pts = sorted(points, key=lambda tp: tp[0])
    times = [t for t, _ in pts]
    probs = [p for _, p in pts]

    if resolved_at < times[0]:
        raise ValueError("resolved_at precedes the first forecast point")

    boundaries = times[1:] + [resolved_at]
    durations = [
        (end - start).total_seconds()
        for start, end in zip(times, boundaries)
    ]
    total = sum(durations)
    if total <= 0:
        # All points collapse onto one instant (or resolution == first point):
        # fall back to the last (most recent) forecast.
        return brier(probs[-1], outcome)

    return sum(
        (d / total) * brier(p, outcome)
        for d, p in zip(durations, probs)
    )


def log_score(p: float, outcome: int) -> float:
    """Negative log-likelihood of the outcome, clipped to ``[1e-4, 1-1e-4]``.

    Oriented so lower is better (0 = perfect); a confident miss is bounded at
    ``-log(1e-4)`` rather than infinite (§2.3).
    """
    q = min(max(p, _LOG_CLIP), 1.0 - _LOG_CLIP)
    prob_of_outcome = q if outcome == 1 else 1.0 - q
    return -math.log(prob_of_outcome)


class ECEResult(BaseModel):
    """Expected Calibration Error with per-bin detail (§2.3).

    ``bins`` holds one dict per bin with keys ``lo``, ``hi``, ``count``,
    ``mean_p``, ``observed``, ``wilson_lo``, ``wilson_hi``. ``ece`` is the
    count-weighted mean absolute gap between mean forecast and observed
    frequency.
    """

    bins: list[dict]
    ece: float


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    lo = max(0.0, center - margin)
    hi = min(1.0, center + margin)
    return (lo, hi)


def ece(pairs: list[tuple[float, int]], bins: int = 10) -> ECEResult:
    """Expected Calibration Error over ``bins`` equal-width probability bins.

    Forecasts are bucketed by stated probability into ``[k/bins, (k+1)/bins)``
    (the top bin is closed on the right so ``p == 1`` lands in it). Each bin
    reports its count, mean forecast, observed frequency, and a Wilson score
    interval around the observed frequency (§2.3, binomial error bars).
    """
    if bins <= 0:
        raise ValueError("bins must be positive")

    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, o in pairs:
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, o))

    n_total = len(pairs)
    out_bins: list[dict] = []
    ece_val = 0.0
    for k, bucket in enumerate(buckets):
        lo_edge = k / bins
        hi_edge = (k + 1) / bins
        count = len(bucket)
        if count:
            mean_p = sum(p for p, _ in bucket) / count
            successes = sum(o for _, o in bucket)
            observed = successes / count
            w_lo, w_hi = _wilson_interval(successes, count)
            ece_val += (count / n_total) * abs(mean_p - observed)
        else:
            mean_p = 0.0
            observed = 0.0
            w_lo, w_hi = 0.0, 0.0
        out_bins.append(
            {
                "lo": lo_edge,
                "hi": hi_edge,
                "count": count,
                "mean_p": mean_p,
                "observed": observed,
                "wilson_lo": w_lo,
                "wilson_hi": w_hi,
            }
        )

    return ECEResult(bins=out_bins, ece=ece_val)


def skill_score(bs_system: float, bs_reference: float) -> float:
    """Brier skill score vs a reference: ``1 - bs_system / bs_reference`` (§2.3).

    Positive means the system beats the reference; 0 means parity.
    """
    if bs_reference == 0:
        raise ValueError("reference Brier is zero; skill score undefined")
    return 1.0 - bs_system / bs_reference


def murphy_decomposition(
    pairs: list[tuple[float, int]],
) -> tuple[float, float, float]:
    """Murphy decomposition of the mean Brier: ``(reliability, resolution,
    uncertainty)`` (§2.3).

    Forecasts are grouped by their exact stated probability so the identity
    ``mean_brier == reliability - resolution + uncertainty`` holds exactly.
    Reliability (lower better) measures within-group miscalibration; resolution
    (higher better) measures how far group outcome rates spread from the base
    rate; uncertainty is the base-rate variance ``o_bar * (1 - o_bar)``.
    """
    if not pairs:
        raise ValueError("murphy_decomposition requires at least one pair")

    n = len(pairs)
    o_bar = sum(o for _, o in pairs) / n

    groups: dict[float, list[int]] = {}
    for p, o in pairs:
        groups.setdefault(p, []).append(o)

    reliability = 0.0
    resolution = 0.0
    for p, outcomes in groups.items():
        nk = len(outcomes)
        ok = sum(outcomes) / nk
        reliability += nk * (p - ok) ** 2
        resolution += nk * (ok - o_bar) ** 2
    reliability /= n
    resolution /= n
    uncertainty = o_bar * (1.0 - o_bar)

    return (reliability, resolution, uncertainty)


def bootstrap_ci(
    values: list[float],
    n: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of ``values`` (§9.4).

    Resamples with replacement ``n`` times using ``np.random.default_rng(seed)``
    (deterministic per seed) and returns the ``[alpha/2, 1-alpha/2]`` percentile
    interval of the resampled means.
    """
    if not values:
        raise ValueError("bootstrap_ci requires at least one value")

    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n, arr.size))
    means = arr[idx].mean(axis=1)
    lo = float(np.percentile(means, 100 * (alpha / 2)))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return (lo, hi)


def paper_trade(
    p_oracle: float,
    p_market: float,
    outcome: int,
    kelly_fraction: float = 0.25,
) -> "TradeResult":
    """Fractional-Kelly paper trade of Oracle's divergence from a market (§9.4).

    Bet direction is the sign of ``p_oracle - p_market``; if the edge is below
    ``1e-6`` we decline to bet. Stake is ``kelly_fraction`` of the full Kelly
    fraction sized at the market price; ``payoff`` is the net wealth change on
    ``outcome`` and ``log_wealth_delta = log(1 + payoff)``. Not a proper scoring
    rule — reported on a separate track, never blended with Brier.
    """
    from oracle.models import TradeResult

    edge = p_oracle - p_market
    if abs(edge) < _NO_BET_EPS:
        return TradeResult(
            direction="none",
            stake=0.0,
            entry_price=p_market,
            payoff=0.0,
            log_wealth_delta=0.0,
        )

    if edge > 0:
        # Buy YES at p_market: full Kelly f = (p_o - p_m)/(1 - p_m);
        # net odds b = (1 - p_m)/p_m; win iff outcome == 1.
        direction = "yes"
        entry_price = p_market
        full_kelly = (p_oracle - p_market) / (1.0 - p_market)
        net_odds = (1.0 - p_market) / p_market
        won = outcome == 1
    else:
        # Buy NO at (1 - p_market): full Kelly f = (p_m - p_o)/p_m;
        # net odds b = p_m/(1 - p_m); win iff outcome == 0.
        direction = "no"
        entry_price = 1.0 - p_market
        full_kelly = (p_market - p_oracle) / p_market
        net_odds = p_market / (1.0 - p_market)
        won = outcome == 0

    stake = kelly_fraction * full_kelly
    stake = min(max(stake, 0.0), 1.0)
    payoff = stake * net_odds if won else -stake
    log_wealth_delta = math.log(1.0 + payoff)

    return TradeResult(
        direction=direction,
        stake=stake,
        entry_price=entry_price,
        payoff=payoff,
        log_wealth_delta=log_wealth_delta,
    )


def log_wealth(trades: list["TradeResult"]) -> list[float]:
    """Cumulative log-wealth curve from a sequence of trades (§9.4).

    Returns the running sum of each trade's ``log_wealth_delta``; empty in,
    empty out.
    """
    curve: list[float] = []
    running = 0.0
    for tr in trades:
        running += tr.log_wealth_delta
        curve.append(running)
    return curve
