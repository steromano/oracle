import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oracle.aggregation import (
    pool,
    pool_geo_mean_odds,
    pool_median,
    pool_trimmed_mean,
)

# Probabilities constrained away from the exact {0,1} edges so that the
# internal odds-space clipping in geo_mean_odds cannot push a result a hair
# outside the [min,max] of the inputs.
prob = st.floats(min_value=1e-3, max_value=1 - 1e-3)
prob_list = st.lists(prob, min_size=1, max_size=20)


@given(prob_list)
@settings(max_examples=300)
def test_all_pools_in_unit_interval(ps):
    for value in (pool_median(ps), pool_trimmed_mean(ps), pool_geo_mean_odds(ps)):
        assert 0.0 <= value <= 1.0


@given(prob_list)
@settings(max_examples=300)
def test_all_pools_within_min_max(ps):
    lo, hi = min(ps), max(ps)
    eps = 1e-9
    for value in (pool_median(ps), pool_trimmed_mean(ps), pool_geo_mean_odds(ps)):
        assert lo - eps <= value <= hi + eps


def test_pool_median_single():
    assert pool_median([0.5]) == 0.5


def test_pool_median_basic():
    assert pool_median([0.2, 0.8]) == pytest.approx(0.5)
    assert pool_median([0.1, 0.4, 0.9]) == pytest.approx(0.4)


def test_pool_trimmed_mean_trims_ends():
    # 0.2 trim on 5 elements drops one from each end -> mean of middle three.
    ps = [0.0 + 1e-3, 0.3, 0.4, 0.5, 1.0 - 1e-3]
    assert pool_trimmed_mean(ps, trim=0.2) == pytest.approx((0.3 + 0.4 + 0.5) / 3)


def test_pool_geo_mean_odds_identical():
    assert pool_geo_mean_odds([0.7, 0.7, 0.7]) == pytest.approx(0.7)
    assert pool_geo_mean_odds([0.42]) == pytest.approx(0.42)


def test_pool_geo_mean_odds_known_value():
    # odds(0.2)=0.25, odds(0.8)=4.0 -> geo mean odds = 1.0 -> prob 0.5
    assert pool_geo_mean_odds([0.2, 0.8]) == pytest.approx(0.5)


@given(prob_list, prob, st.integers(min_value=0, max_value=19))
@settings(max_examples=200)
def test_median_monotonic_raising_input(ps, bump, idx):
    idx = idx % len(ps)
    before = pool_median(ps)
    raised = list(ps)
    raised[idx] = min(1.0, ps[idx] + abs(bump - ps[idx]))
    after = pool_median(raised)
    assert after >= before - 1e-12


def test_pool_dispatch_matches_helpers():
    ps = [0.2, 0.5, 0.9]
    assert pool(ps, "median") == pytest.approx(pool_median(ps))
    assert pool(ps, "trimmed") == pytest.approx(pool_trimmed_mean(ps))
    assert pool(ps, "geo_odds") == pytest.approx(pool_geo_mean_odds(ps))


def test_pool_market_weight_one_adds_one_vote():
    ps = [0.2, 0.8]
    # Without the market, median is 0.5.
    assert pool(ps, "median") == pytest.approx(0.5)
    # A single market vote at 0.9 makes it the median of [0.2, 0.8, 0.9] = 0.8.
    assert pool(ps, "median", market_price=0.9, market_weight=1.0) == pytest.approx(0.8)


def test_pool_market_weight_two_adds_two_votes():
    ps = [0.2, 0.8]
    # Two market votes at 0.9 -> median of [0.2, 0.8, 0.9, 0.9] = 0.85.
    got = pool(ps, "median", market_price=0.9, market_weight=2.0)
    assert got == pytest.approx(0.85)


def test_pool_no_market_when_price_none():
    ps = [0.2, 0.8, 0.9]
    assert pool(ps, "median", market_price=None) == pytest.approx(pool_median(ps))


def test_pool_unknown_method_raises():
    with pytest.raises(ValueError):
        pool([0.5], "nonsense")  # type: ignore[arg-type]
