import numpy as np
import pytest
from scipy.stats import weibull_min

from hria.stats.lifetime import (
    acceleration_factor,
    equivalent_use_duration,
    fit_weibull_censored,
    weibull_log_likelihood,
)
from hria.stats.multiple import benjamini_hochberg
from hria.stats.proportions import wilson_interval
from hria.stats.survival import kaplan_meier_at, log_rank_test
from hria.stats.trend import measurement_trend


def test_wilson_interval_known_answer() -> None:
    result = wilson_interval(5, 10)
    assert result.proportion == 0.5
    assert result.confidence_interval == pytest.approx((0.236593, 0.763407), abs=1e-6)


def test_censored_weibull_recovers_seeded_parameters() -> None:
    rng = np.random.default_rng(4471)
    beta, eta = 2.2, 1_200.0
    true_life = eta * rng.weibull(beta, 8_000)
    censor_at = rng.uniform(500, 1_100, len(true_life))
    observed = np.minimum(true_life, censor_at)
    events = true_life <= censor_at

    fit = fit_weibull_censored(observed, events)

    assert fit.beta == pytest.approx(beta, rel=0.05)
    assert fit.eta == pytest.approx(eta, rel=0.05)
    assert fit.n_failed == int(events.sum())
    assert fit.method == "mle_censored"


def test_ignoring_censoring_biases_lifetime_scale_downward() -> None:
    rng = np.random.default_rng(73)
    beta, eta = 1.7, 2_000.0
    life = eta * rng.weibull(beta, 10_000)
    observed = np.minimum(life, 900.0)
    events = life <= 900.0

    censored_fit = fit_weibull_censored(observed, events)
    _, _, naive_eta = weibull_min.fit(observed[events], floc=0)

    assert censored_fit.eta == pytest.approx(eta, rel=0.06)
    assert naive_eta < censored_fit.eta * 0.6


def test_log_likelihood_rejects_nonpositive_durations() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        weibull_log_likelihood(np.log([2.0, 100.0]), [10.0, 0.0], [True, False])


def test_arrhenius_voltage_acceleration_direction() -> None:
    factor = acceleration_factor(
        stress_temp_c=[85.0],
        use_temp_c=25.0,
        stress_voltage_v=[5.5],
        use_voltage_v=3.3,
    )
    assert factor[0] > 1.0
    assert equivalent_use_duration([100.0], factor)[0] > 100.0


def test_kaplan_meier_uses_censored_risk_sets() -> None:
    result = kaplan_meier_at([1, 2, 3, 4], [True, False, True, False], 3)
    assert result.survival == pytest.approx(0.375)
    assert result.failure_probability == pytest.approx(0.625)
    assert result.events_before_horizon == 2


def test_log_rank_identical_groups_are_not_different() -> None:
    durations = [1, 2, 3, 4, 5]
    events = [True, True, False, True, False]
    result = log_rank_test(durations, events, durations, events)
    assert result.chi_square == pytest.approx(0.0)
    assert result.p_value == pytest.approx(1.0)


def test_benjamini_hochberg_known_answer() -> None:
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, 0.002])
    assert adjusted == pytest.approx([0.02, 0.04, 0.04, 0.008])


def test_measurement_trend_enforces_evidence_floor() -> None:
    with pytest.raises(ValueError, match="20 points"):
        measurement_trend(np.arange(10), np.arange(10))


def test_measurement_trend_recovers_slope() -> None:
    days = np.linspace(0, 30, 100)
    residuals = 0.05 * days + np.sin(days) * 0.01
    result = measurement_trend(days, residuals)
    assert result.slope_per_day == pytest.approx(0.05, rel=0.02)
