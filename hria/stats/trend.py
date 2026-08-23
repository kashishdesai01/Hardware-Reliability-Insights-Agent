from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike
from scipy.stats import linregress


@dataclass(frozen=True)
class TrendResult:
    slope_per_day: float
    slope_ci: tuple[float, float]
    p_value: float
    breakpoint_day: float | None
    n_points: int
    span_days: float
    method: str = "linear_residual_trend"


def measurement_trend(days: ArrayLike, residuals: ArrayLike) -> TrendResult:
    x = np.asarray(days, dtype=float)
    y = np.asarray(residuals, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError("days and residuals must be equal-length one-dimensional arrays")
    if len(x) < 20:
        raise ValueError("at least 20 points are required")
    span = float(np.max(x) - np.min(x))
    if span < 14:
        raise ValueError("at least 14 days of observations are required")
    fit = linregress(x, y)
    slope_ci = (fit.slope - 1.96 * fit.stderr, fit.slope + 1.96 * fit.stderr)

    breakpoint = None
    best_error = float("inf")
    order = np.argsort(x)
    sx, sy = x[order], y[order]
    for split in range(max(10, len(x) // 5), min(len(x) - 10, len(x) * 4 // 5)):
        left = linregress(sx[:split], sy[:split])
        right = linregress(sx[split:], sy[split:])
        error = float(
            np.sum((sy[:split] - (left.intercept + left.slope * sx[:split])) ** 2)
            + np.sum((sy[split:] - (right.intercept + right.slope * sx[split:])) ** 2)
        )
        if error < best_error:
            best_error = error
            breakpoint = float(sx[split])
    return TrendResult(
        slope_per_day=float(fit.slope),
        slope_ci=(float(slope_ci[0]), float(slope_ci[1])),
        p_value=float(fit.pvalue),
        breakpoint_day=breakpoint,
        n_points=len(x),
        span_days=span,
    )
