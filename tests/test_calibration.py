"""Tests for src/oracle/calibration.py (Task 4).

Covers the pure ``extremize`` transform, LOO-selected recalibration fitting
(refusing N<50, recovering alpha>1 on underconfident data and improving Brier),
``apply``, and versioned JSON persistence / active-map loading.
"""

from __future__ import annotations

import math

import pytest

from oracle.calibration import (
    CalibrationMap,
    apply,
    extremize,
    fit_recalibration,
    load_active_map,
    save_map,
)


# --- extremize ------------------------------------------------------------


@pytest.mark.parametrize("p", [0.0, 0.01, 0.2, 0.37, 0.5, 0.63, 0.8, 0.99, 1.0])
def test_extremize_identity_at_alpha_one(p: float) -> None:
    assert extremize(p, 1.0) == pytest.approx(p)


def test_extremize_fixed_points():
    # 0, 0.5, 1 are fixed points for any alpha.
    for alpha in (0.5, 1.0, 2.0, 3.5):
        assert extremize(0.0, alpha) == pytest.approx(0.0)
        assert extremize(0.5, alpha) == pytest.approx(0.5)
        assert extremize(1.0, alpha) == pytest.approx(1.0)


def test_extremize_monotone_increasing_in_p():
    alpha = 2.5
    ps = [0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95]
    ys = [extremize(p, alpha) for p in ps]
    # strictly increasing → order-preserving
    for a, b in zip(ys, ys[1:]):
        assert a < b


def test_extremize_pushes_away_from_half_when_alpha_gt_one():
    # alpha > 1 extremizes: values above 0.5 rise, below 0.5 fall.
    assert extremize(0.7, 2.0) > 0.7
    assert extremize(0.3, 2.0) < 0.3


# --- fit_recalibration ----------------------------------------------------


def _underconfident_pairs() -> list[tuple[float, int]]:
    """50 symmetric, underconfident pairs.

    Forecaster reports 0.7 but YES occurs 21/25 (0.84); reports 0.3 but YES
    occurs 4/25 (0.16). The optimal single-parameter extremization
    (alpha ~= 1.96) maps 0.7 -> 0.84, lowering Brier.
    """
    pairs: list[tuple[float, int]] = []
    pairs += [(0.7, 1)] * 21 + [(0.7, 0)] * 4
    pairs += [(0.3, 1)] * 4 + [(0.3, 0)] * 21
    return pairs


def test_fit_refuses_small_n():
    pairs = _underconfident_pairs()[:49]
    assert len(pairs) == 49
    with pytest.raises(ValueError):
        fit_recalibration(pairs)


def test_fit_recovers_extremization_on_underconfident_data():
    pairs = _underconfident_pairs()
    assert len(pairs) == 50
    m = fit_recalibration(pairs)
    assert m.fitted_on_n == 50
    # Symmetric underconfident data → extremize map with alpha > 1.
    assert m.kind == "extremize"
    assert m.alpha is not None and m.alpha > 1.0
    # Recalibration must not worsen (here: strictly improve) LOO Brier.
    assert m.loo_brier_after <= m.loo_brier_before
    assert m.loo_brier_after < m.loo_brier_before  # strict on this data
    # id shape and tz-aware created_at.
    assert m.id.startswith("cal-")
    assert m.created_at.tzinfo is not None


def test_apply_matches_extremize_for_extremize_map():
    pairs = _underconfident_pairs()
    m = fit_recalibration(pairs)
    assert m.kind == "extremize" and m.alpha is not None
    for p in (0.2, 0.55, 0.81):
        assert apply(m, p) == pytest.approx(extremize(p, m.alpha))


def test_apply_platt_map():
    m = CalibrationMap(
        id="cal-20260101-001",
        kind="platt",
        platt_a=1.5,
        platt_b=0.2,
        fitted_on_n=60,
        loo_brier_before=0.2,
        loo_brier_after=0.18,
        created_at="2026-01-01T00:00:00Z",
    )
    p = 0.6
    logit = math.log(p / (1 - p))
    expected = 1.0 / (1.0 + math.exp(-(1.5 * logit + 0.2)))
    assert apply(m, p) == pytest.approx(expected)


# --- persistence ----------------------------------------------------------


def test_save_and_load_active_map(state_root):
    cal_dir = state_root / "data" / "benchmarks" / "calibration"
    assert load_active_map(cal_dir) is None

    m = fit_recalibration(_underconfident_pairs())
    path = save_map(m, cal_dir)
    assert path.exists()
    assert path.name == f"{m.id}.json"

    loaded = load_active_map(cal_dir)
    assert loaded is not None
    assert loaded.id == m.id
    assert loaded.alpha == pytest.approx(m.alpha)


def test_load_active_map_returns_latest(state_root):
    cal_dir = state_root / "data" / "benchmarks" / "calibration"
    older = CalibrationMap(
        id="cal-20260101-001",
        kind="extremize",
        alpha=1.2,
        fitted_on_n=50,
        loo_brier_before=0.2,
        loo_brier_after=0.19,
        created_at="2026-01-01T00:00:00Z",
    )
    newer = CalibrationMap(
        id="cal-20260601-001",
        kind="extremize",
        alpha=1.8,
        fitted_on_n=80,
        loo_brier_before=0.2,
        loo_brier_after=0.17,
        created_at="2026-06-01T00:00:00Z",
    )
    save_map(older, cal_dir)
    save_map(newer, cal_dir)
    active = load_active_map(cal_dir)
    assert active is not None
    assert active.id == newer.id
