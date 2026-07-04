"""Tests for oracle.scoring (T2) — brier, stream-brier, log, ece, murphy,
skill, bootstrap, paper-trade, log-wealth.

All datetimes are tz-aware UTC (Global Constraints).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from hypothesis import given, strategies as st

from oracle.models import TradeResult
from oracle.scoring import (
    ECEResult,
    bootstrap_ci,
    brier,
    ece,
    log_score,
    log_wealth,
    murphy_decomposition,
    paper_trade,
    skill_score,
    stream_brier,
)

UTC = timezone.utc


# ---------------------------------------------------------------- brier


@given(st.floats(0, 1))
def test_brier_bounds(p):
    assert 0 <= brier(p, 1) <= 1
    assert 0 <= brier(p, 0) <= 1


def test_brier_perfect():
    assert brier(1, 1) == 0
    assert brier(0, 0) == 0


def test_brier_ignorance():
    assert brier(0.5, 1) == 0.25
    assert brier(0.5, 0) == 0.25


def test_brier_worst():
    assert brier(1, 0) == 1
    assert brier(0, 1) == 1


# ---------------------------------------------------------- stream_brier


def test_stream_reduces_to_brier():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r = datetime(2026, 1, 11, tzinfo=UTC)
    assert abs(stream_brier([(t0, 0.7)], r, 1) - brier(0.7, 1)) < 1e-12


def test_stream_time_weighting():
    # 0.9 held 1 day then 0.1 held 9 days, outcome 0.
    # weights: 1/10 on brier(0.9,0)=0.81 ; 9/10 on brier(0.1,0)=0.01
    # => 0.1*0.81 + 0.9*0.01 = 0.081 + 0.009 = 0.09  (closer to brier(0.1,0)).
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [(t0, 0.9), (t0 + timedelta(days=1), 0.1)]
    r = t0 + timedelta(days=10)
    got = stream_brier(pts, r, 0)
    assert abs(got - 0.09) < 1e-12
    assert abs(got - brier(0.1, 0)) < abs(got - brier(0.9, 0))


def test_stream_unsorted_input_is_sorted():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    a = (t0, 0.9)
    b = (t0 + timedelta(days=1), 0.1)
    r = t0 + timedelta(days=10)
    assert abs(stream_brier([b, a], r, 0) - stream_brier([a, b], r, 0)) < 1e-12


def test_stream_equal_intervals_is_mean():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [(t0, 0.8), (t0 + timedelta(days=5), 0.2)]
    r = t0 + timedelta(days=10)
    # equal 5-day intervals => simple mean of the two brier components, outcome 1
    expected = 0.5 * brier(0.8, 1) + 0.5 * brier(0.2, 1)
    assert abs(stream_brier(pts, r, 1) - expected) < 1e-12


# ------------------------------------------------------------- log_score


def test_log_score_near_perfect():
    # p is clipped to [1e-4, 1-1e-4] (§2.3), so a "perfect" call scores the
    # tiny bounded penalty -log(1-1e-4), not exactly 0.
    assert abs(log_score(1, 1) - (-math.log(1 - 1e-4))) < 1e-12
    assert abs(log_score(0, 0) - (-math.log(1 - 1e-4))) < 1e-12
    assert log_score(1, 1) < 1e-3


def test_log_score_clipped():
    # confident-and-wrong is clipped to -log(1e-4), not infinite.
    assert math.isfinite(log_score(0, 1))
    assert abs(log_score(0, 1) - (-math.log(1e-4))) < 1e-9


def test_log_score_lower_is_better():
    assert log_score(0.9, 1) < log_score(0.6, 1)


# ------------------------------------------------------------------- ece


def test_ece_perfect_calibration_is_zero():
    # In each bin the observed frequency equals the forecast probability.
    pairs = [(0.1, 0)] * 9 + [(0.1, 1)] * 1  # bin freq 0.1
    pairs += [(0.9, 1)] * 9 + [(0.9, 0)] * 1  # bin freq 0.9
    res = ece(pairs, bins=10)
    assert isinstance(res, ECEResult)
    assert res.ece < 1e-9


def test_ece_detects_miscalibration():
    # forecast 0.9 but outcome always 0 => big gap.
    res = ece([(0.9, 0)] * 20, bins=10)
    assert abs(res.ece - 0.9) < 1e-9


def test_ece_bins_have_wilson_bounds():
    res = ece([(0.9, 1)] * 5 + [(0.9, 0)] * 5, bins=10)
    filled = [b for b in res.bins if b["count"] > 0]
    assert filled
    for b in filled:
        assert b["wilson_lo"] <= b["wilson_hi"]
        assert 0.0 <= b["wilson_lo"] <= 1.0
        assert 0.0 <= b["wilson_hi"] <= 1.0


# ----------------------------------------------------------- skill_score


def test_skill_score():
    # system half the reference brier => skill 0.5
    assert skill_score(0.1, 0.2) == 0.5
    # equal to reference => 0 skill
    assert skill_score(0.2, 0.2) == 0.0


# --------------------------------------------------- murphy_decomposition


def test_murphy_sums_to_brier():
    pairs = [(0.2, 0), (0.2, 1), (0.8, 1), (0.8, 0), (0.5, 1), (0.5, 0)]
    rel, res, unc = murphy_decomposition(pairs)
    mean_brier = sum(brier(p, o) for p, o in pairs) / len(pairs)
    assert abs((rel - res + unc) - mean_brier) < 1e-9
    assert rel >= 0 and res >= 0 and unc >= 0


def test_murphy_uncertainty_is_base_rate_variance():
    pairs = [(0.3, 1), (0.7, 1), (0.4, 0), (0.6, 0)]  # base rate 0.5
    _, _, unc = murphy_decomposition(pairs)
    assert abs(unc - 0.25) < 1e-12


# ------------------------------------------------------------ bootstrap


def test_bootstrap_order():
    lo, hi = bootstrap_ci([0.1, 0.2, 0.3], seed=0)
    assert lo <= hi


def test_bootstrap_deterministic_with_seed():
    v = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert bootstrap_ci(v, seed=0) == bootstrap_ci(v, seed=0)


def test_bootstrap_brackets_mean():
    v = [0.1, 0.2, 0.3, 0.4, 0.5]  # mean 0.3
    lo, hi = bootstrap_ci(v, seed=0)
    assert lo <= 0.3 <= hi


def test_bootstrap_constant_is_degenerate():
    lo, hi = bootstrap_ci([0.42, 0.42, 0.42], seed=1)
    assert abs(lo - 0.42) < 1e-12 and abs(hi - 0.42) < 1e-12


# ----------------------------------------------------------- paper_trade


@given(st.floats(0.01, 0.99), st.floats(0.01, 0.99))
def test_paper_trade_no_bet_when_agree(p, q):
    # |p-q| < 1e-6 => no bet.
    if abs(p - q) < 1e-6:
        tr = paper_trade(p, q, 1)
        assert tr.direction == "none"
        assert tr.stake == 0.0
        assert tr.payoff == 0.0
        assert tr.log_wealth_delta == 0.0


def test_paper_trade_agree_exact():
    tr = paper_trade(0.5, 0.5, 1)
    assert tr.direction == "none"
    assert tr.stake == 0.0
    assert tr.log_wealth_delta == 0.0


def test_paper_trade_yes_win():
    # oracle 0.8 > market 0.5, quarter kelly.
    # full kelly f = (p_o - p_m)/(1 - p_m) = 0.3/0.5 = 0.6
    # stake = 0.25 * 0.6 = 0.15
    # net odds b = (1-p_m)/p_m = 1.0 ; outcome yes => payoff = stake*b = 0.15
    tr = paper_trade(0.8, 0.5, 1, kelly_fraction=0.25)
    assert tr.direction == "yes"
    assert abs(tr.stake - 0.15) < 1e-12
    assert abs(tr.entry_price - 0.5) < 1e-12
    assert abs(tr.payoff - 0.15) < 1e-12
    assert abs(tr.log_wealth_delta - math.log(1 + 0.15)) < 1e-12


def test_paper_trade_yes_loss():
    # same trade but outcome no => lose the stake.
    tr = paper_trade(0.8, 0.5, 0, kelly_fraction=0.25)
    assert tr.direction == "yes"
    assert abs(tr.stake - 0.15) < 1e-12
    assert abs(tr.payoff - (-0.15)) < 1e-12
    assert abs(tr.log_wealth_delta - math.log(1 - 0.15)) < 1e-12


def test_paper_trade_no_direction_win():
    # oracle 0.2 < market 0.5 => bet NO.
    # full kelly f = (p_m - p_o)/p_m = 0.3/0.5 = 0.6 ; stake = 0.15
    # net odds b_no = p_m/(1-p_m) = 1.0 ; outcome no => payoff = 0.15
    tr = paper_trade(0.2, 0.5, 0, kelly_fraction=0.25)
    assert tr.direction == "no"
    assert abs(tr.stake - 0.15) < 1e-12
    assert abs(tr.payoff - 0.15) < 1e-12
    assert abs(tr.log_wealth_delta - math.log(1 + 0.15)) < 1e-12


def test_paper_trade_returns_traderesult():
    assert isinstance(paper_trade(0.7, 0.4, 1), TradeResult)


# ------------------------------------------------------------ log_wealth


def test_log_wealth_cumulative():
    trades = [
        paper_trade(0.8, 0.5, 1),  # win
        paper_trade(0.8, 0.5, 0),  # loss
    ]
    curve = log_wealth(trades)
    assert len(curve) == 2
    assert abs(curve[0] - trades[0].log_wealth_delta) < 1e-12
    assert abs(curve[1] - (trades[0].log_wealth_delta + trades[1].log_wealth_delta)) < 1e-12


def test_log_wealth_empty():
    assert log_wealth([]) == []
