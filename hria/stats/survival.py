from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt

import numpy as np
from numpy.typing import ArrayLike
from scipy.stats import chi2, norm


@dataclass(frozen=True)
class SurvivalAtTime:
    horizon: float
    survival: float
    failure_probability: float
    confidence_interval: tuple[float, float]
    at_risk: int
    events_before_horizon: int
    method: str = "kaplan_meier_greenwood"


@dataclass(frozen=True)
class LogRankResult:
    chi_square: float
    p_value: float
    observed_a: int
    expected_a: float
    method: str = "log_rank"


def kaplan_meier_at(
    durations: ArrayLike, events: ArrayLike, horizon: float, confidence: float = 0.95
) -> SurvivalAtTime:
    time = np.asarray(durations, dtype=float)
    event = np.asarray(events, dtype=bool)
    if time.shape != event.shape or time.ndim != 1 or len(time) == 0:
        raise ValueError("durations and events must be non-empty equal-length arrays")
    if horizon <= 0 or np.any(time <= 0):
        raise ValueError("horizon and durations must be positive")
    survival = 1.0
    greenwood_sum = 0.0
    event_count = 0
    for current in np.unique(time[(event) & (time <= horizon)]):
        at_risk = int(np.sum(time >= current))
        failures = int(np.sum((time == current) & event))
        survival *= 1.0 - failures / at_risk
        event_count += failures
        if at_risk > failures:
            greenwood_sum += failures / (at_risk * (at_risk - failures))
    z_value = float(norm.ppf(0.5 + confidence / 2.0))
    if survival in (0.0, 1.0) or greenwood_sum == 0:
        lower_s, upper_s = survival, survival
    else:
        log_log = log(-log(survival))
        se_log_log = sqrt(greenwood_sum) / abs(log(survival))
        lower_s = exp(-exp(log_log + z_value * se_log_log))
        upper_s = exp(-exp(log_log - z_value * se_log_log))
    return SurvivalAtTime(
        horizon=horizon,
        survival=survival,
        failure_probability=1.0 - survival,
        confidence_interval=(1.0 - upper_s, 1.0 - lower_s),
        at_risk=int(np.sum(time >= horizon)),
        events_before_horizon=event_count,
    )


def log_rank_test(
    durations_a: ArrayLike, events_a: ArrayLike, durations_b: ArrayLike, events_b: ArrayLike
) -> LogRankResult:
    ta = np.asarray(durations_a, dtype=float)
    ea = np.asarray(events_a, dtype=bool)
    tb = np.asarray(durations_b, dtype=float)
    eb = np.asarray(events_b, dtype=bool)
    if ta.shape != ea.shape or tb.shape != eb.shape or ta.ndim != 1 or tb.ndim != 1:
        raise ValueError("each duration/event pair must have matching one-dimensional shapes")
    observed_a = 0.0
    expected_a = 0.0
    variance = 0.0
    for current in np.unique(np.concatenate([ta[ea], tb[eb]])):
        risk_a = int(np.sum(ta >= current))
        risk_b = int(np.sum(tb >= current))
        failures_a = int(np.sum((ta == current) & ea))
        failures_b = int(np.sum((tb == current) & eb))
        risk_total = risk_a + risk_b
        failures_total = failures_a + failures_b
        if risk_total == 0:
            continue
        observed_a += failures_a
        expected_a += failures_total * risk_a / risk_total
        if risk_total > 1:
            variance += (
                risk_a
                * risk_b
                * failures_total
                * (risk_total - failures_total)
                / (risk_total**2 * (risk_total - 1))
            )
    statistic = (observed_a - expected_a) ** 2 / variance if variance > 0 else 0.0
    return LogRankResult(
        chi_square=float(statistic),
        p_value=float(chi2.sf(statistic, 1)),
        observed_a=int(observed_a),
        expected_a=float(expected_a),
    )
