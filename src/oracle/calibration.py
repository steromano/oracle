"""Statistical post-hoc recalibration (§6.3, §9.5).

Corrects the system's measured miscalibration with a monotone transform fitted
on resolved ``(probability, outcome)`` pairs. Two transform families are
supported, both monotone and both special/general cases of logit-space scaling:

- ``extremize`` — odds-space extremization ``p' = p^a / (p^a + (1-p)^a)``,
  equivalently ``sigmoid(a * logit(p))``. One parameter.
- ``platt`` — logistic scaling ``p' = sigmoid(a * logit(p) + b)``. Two
  parameters (adds a bias term).

The fit selects between them by leave-one-out (LOO) Brier and refuses to run
with fewer than 50 resolutions (the fit is meaningless below that, §6.3).
Extremization is preferred on a near-tie because it is the simpler model and is
the documented LLM correction (underconfidence, §5.9). Maps are versioned JSON
artifacts under ``data/benchmarks/calibration/`` referenced by id in every
ForecastRecord they touch.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from scipy.optimize import minimize, minimize_scalar

from oracle.models import UTCModel

MIN_FIT_N = 50
_EPS = 1e-6
_ALPHA_BOUNDS = (0.2, 8.0)
# Extremize is chosen unless Platt beats it by more than this LOO-Brier margin.
_PREFER_EXTREMIZE_MARGIN = 1e-9


class CalibrationMap(UTCModel):
    """A fitted, versioned recalibration transform (§6.3)."""

    id: str  # "cal-YYYYMMDD-NNN"
    kind: Literal["extremize", "platt"]
    alpha: float | None = None
    platt_a: float | None = None
    platt_b: float | None = None
    fitted_on_n: int
    loo_brier_before: float
    loo_brier_after: float
    created_at: datetime


def extremize(p: float, alpha: float) -> float:
    """Odds-space extremization ``p^a / (p^a + (1-p)^a)``.

    ``alpha == 1`` is the identity; ``alpha > 1`` pushes probabilities away
    from 0.5 (extremizing), ``alpha < 1`` pulls them toward it. Monotone
    increasing in ``p`` for ``alpha > 0``; 0, 0.5 and 1 are fixed points.
    """
    pa = p**alpha
    qa = (1.0 - p) ** alpha
    denom = pa + qa
    if denom == 0.0:
        return p
    return pa / denom


def _logit(p: float) -> float:
    p = min(max(p, _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _platt(p: float, a: float, b: float) -> float:
    return _sigmoid(a * _logit(p) + b)


def _mean_brier(pairs: list[tuple[float, int]], transform) -> float:
    return sum((transform(p) - o) ** 2 for p, o in pairs) / len(pairs)


def _fit_alpha(pairs: list[tuple[float, int]]) -> float:
    res = minimize_scalar(
        lambda a: _mean_brier(pairs, lambda p: extremize(p, a)),
        bounds=_ALPHA_BOUNDS,
        method="bounded",
    )
    return float(res.x)


def _fit_platt(pairs: list[tuple[float, int]]) -> tuple[float, float]:
    res = minimize(
        lambda ab: _mean_brier(pairs, lambda p: _platt(p, ab[0], ab[1])),
        x0=[1.0, 0.0],
        method="Nelder-Mead",
    )
    a, b = res.x
    return float(a), float(b)


def _loo_brier(pairs: list[tuple[float, int]], fit_fn, apply_fn) -> float:
    """Leave-one-out Brier for a parametric transform.

    For each point, refit on the other N-1 points and score the held-out
    point with the refitted transform. Honest out-of-sample estimate used
    both to compare transform families and to report ``loo_brier_after``.
    """
    n = len(pairs)
    total = 0.0
    for i in range(n):
        train = pairs[:i] + pairs[i + 1 :]
        params = fit_fn(train)
        p, o = pairs[i]
        total += (apply_fn(params, p) - o) ** 2
    return total / n


def fit_recalibration(pairs: list[tuple[float, int]]) -> CalibrationMap:
    """Fit and LOO-select a recalibration map. Raises ``ValueError`` if N<50."""
    n = len(pairs)
    if n < MIN_FIT_N:
        raise ValueError(
            f"cannot fit recalibration on N={n} resolutions; need >= {MIN_FIT_N}"
        )

    # Identity (raw) LOO Brier: the transform is data-independent, so LOO
    # equals in-sample.
    loo_before = _mean_brier(pairs, lambda p: p)

    loo_ext = _loo_brier(
        pairs,
        fit_fn=_fit_alpha,
        apply_fn=lambda a, p: extremize(p, a),
    )
    loo_platt = _loo_brier(
        pairs,
        fit_fn=_fit_platt,
        apply_fn=lambda ab, p: _platt(p, ab[0], ab[1]),
    )

    now = datetime.now(timezone.utc)
    map_id = f"cal-{now:%Y%m%d}-001"

    if loo_platt < loo_ext - _PREFER_EXTREMIZE_MARGIN:
        a, b = _fit_platt(pairs)
        return CalibrationMap(
            id=map_id,
            kind="platt",
            platt_a=a,
            platt_b=b,
            fitted_on_n=n,
            loo_brier_before=loo_before,
            loo_brier_after=loo_platt,
            created_at=now,
        )

    alpha = _fit_alpha(pairs)
    return CalibrationMap(
        id=map_id,
        kind="extremize",
        alpha=alpha,
        fitted_on_n=n,
        loo_brier_before=loo_before,
        loo_brier_after=loo_ext,
        created_at=now,
    )


def apply(m: CalibrationMap, p: float) -> float:
    """Apply a fitted map to a probability."""
    if m.kind == "extremize":
        if m.alpha is None:
            raise ValueError(f"extremize map {m.id} missing alpha")
        return extremize(p, m.alpha)
    if m.kind == "platt":
        if m.platt_a is None or m.platt_b is None:
            raise ValueError(f"platt map {m.id} missing platt_a/platt_b")
        return _platt(p, m.platt_a, m.platt_b)
    raise ValueError(f"unknown calibration kind: {m.kind!r}")


def save_map(m: CalibrationMap, dir: Path) -> Path:
    """Write the map to ``<dir>/<id>.json`` and return the path."""
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{m.id}.json"
    path.write_text(m.model_dump_json(indent=2))
    return path


def load_active_map(dir: Path) -> CalibrationMap | None:
    """Return the active (most recently created) map in ``dir``, or None.

    "Active" is defined as the map with the latest ``created_at`` (ties broken
    by id), so re-fitting and saving a newer map activates it.
    """
    dir = Path(dir)
    if not dir.exists():
        return None
    maps = [
        CalibrationMap.model_validate_json(p.read_text())
        for p in dir.glob("cal-*.json")
    ]
    if not maps:
        return None
    return max(maps, key=lambda m: (m.created_at, m.id))
