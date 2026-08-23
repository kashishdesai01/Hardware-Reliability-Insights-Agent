from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize
from scipy.stats import norm

_EPS = np.finfo(float).eps


@dataclass(frozen=True)
class WeibullFit:
    beta: float
    eta: float
    beta_ci: tuple[float, float]
    eta_ci: tuple[float, float]
    b10: float
    b10_ci: tuple[float, float]
    n_failed: int
    n_censored: int
    log_likelihood: float
    method: str = "mle_censored"


def weibull_log_likelihood(
    log_parameters: ArrayLike, durations: ArrayLike, events: ArrayLike
) -> float:
    """Log likelihood for independent exact failures and right-censored observations."""
    log_beta, log_eta = np.asarray(log_parameters, dtype=float)
    beta = np.exp(log_beta)
    time = np.asarray(durations, dtype=float)
    event = np.asarray(events, dtype=bool)
    if time.ndim != 1 or event.ndim != 1 or time.shape != event.shape:
        raise ValueError("durations and events must be equal-length one-dimensional arrays")
    if len(time) == 0 or np.any(~np.isfinite(time)) or np.any(time <= 0):
        raise ValueError("durations must be finite and strictly positive")
    scaled_power = np.exp(np.clip(beta * (np.log(time) - log_eta), -745, 700))
    failure_term = log_beta - log_eta + (beta - 1.0) * (np.log(time) - log_eta)
    return float(np.sum(np.where(event, failure_term, 0.0) - scaled_power))


def _finite_hessian(
    function, point: NDArray[np.float64], step: float = 1e-4
) -> NDArray[np.float64]:
    size = len(point)
    hessian = np.empty((size, size), dtype=float)
    for i in range(size):
        for j in range(size):
            ei = np.zeros(size)
            ej = np.zeros(size)
            ei[i] = step
            ej[j] = step
            hessian[i, j] = (
                function(point + ei + ej)
                - function(point + ei - ej)
                - function(point - ei + ej)
                + function(point - ei - ej)
            ) / (4.0 * step * step)
    return hessian


def fit_weibull_censored(
    durations: ArrayLike,
    events: ArrayLike,
    *,
    confidence: float = 0.95,
    minimum_failures: int = 5,
) -> WeibullFit:
    time = np.asarray(durations, dtype=float)
    event = np.asarray(events, dtype=bool)
    if time.shape != event.shape or time.ndim != 1:
        raise ValueError("durations and events must be equal-length one-dimensional arrays")
    failures = int(event.sum())
    if failures < minimum_failures:
        raise ValueError(f"at least {minimum_failures} failures are required; received {failures}")
    if np.any(time <= 0) or np.any(~np.isfinite(time)):
        raise ValueError("durations must be finite and strictly positive")

    failure_times = time[event]
    initial_beta = 1.5
    initial_eta = float(np.median(failure_times) / (log(2.0) ** (1.0 / initial_beta)))
    initial = np.log([initial_beta, max(initial_eta, _EPS)])

    def objective(value: ArrayLike) -> float:
        return -weibull_log_likelihood(value, time, event)

    result = minimize(objective, initial, method="L-BFGS-B", bounds=[(-6, 6), (-20, 30)])
    if not result.success or np.any(~np.isfinite(result.x)):
        raise RuntimeError(f"censored Weibull fit failed: {result.message}")

    log_beta, log_eta = result.x
    beta, eta = np.exp(result.x)
    hessian = _finite_hessian(objective, result.x)
    try:
        covariance = np.linalg.inv(hessian)
    except np.linalg.LinAlgError as exc:
        raise RuntimeError("censored Weibull fit has a singular covariance matrix") from exc
    if np.any(np.diag(covariance) <= 0):
        raise RuntimeError("censored Weibull fit has a non-positive variance estimate")

    z_value = float(norm.ppf(0.5 + confidence / 2.0))
    standard_errors = np.sqrt(np.diag(covariance))
    beta_ci = tuple(np.exp(log_beta + np.array([-1, 1]) * z_value * standard_errors[0]))
    eta_ci = tuple(np.exp(log_eta + np.array([-1, 1]) * z_value * standard_errors[1]))

    log_probability = log(-log(0.9))
    log_b10 = log_eta + log_probability / beta
    b10_gradient = np.array([-log_probability / beta, 1.0])
    b10_se = sqrt(float(b10_gradient @ covariance @ b10_gradient))
    b10_ci = tuple(np.exp(log_b10 + np.array([-1, 1]) * z_value * b10_se))

    return WeibullFit(
        beta=float(beta),
        eta=float(eta),
        beta_ci=(float(beta_ci[0]), float(beta_ci[1])),
        eta_ci=(float(eta_ci[0]), float(eta_ci[1])),
        b10=float(exp(log_b10)),
        b10_ci=(float(b10_ci[0]), float(b10_ci[1])),
        n_failed=failures,
        n_censored=int((~event).sum()),
        log_likelihood=-float(result.fun),
    )


def acceleration_factor(
    *,
    stress_temp_c: ArrayLike,
    use_temp_c: float,
    stress_voltage_v: ArrayLike,
    use_voltage_v: float,
    activation_energy_ev: float = 0.7,
    voltage_exponent: float = 3.0,
) -> NDArray[np.float64]:
    """Combined Arrhenius and inverse-power acceleration factor."""
    if use_voltage_v <= 0:
        raise ValueError("use voltage must be positive")
    stress_temp_k = np.asarray(stress_temp_c, dtype=float) + 273.15
    use_temp_k = use_temp_c + 273.15
    stress_voltage = np.asarray(stress_voltage_v, dtype=float)
    if np.any(stress_temp_k <= 0) or use_temp_k <= 0 or np.any(stress_voltage <= 0):
        raise ValueError("absolute temperature and voltage must be positive")
    boltzmann_ev_per_k = 8.617333262145e-5
    thermal = np.exp(
        activation_energy_ev / boltzmann_ev_per_k * (1.0 / use_temp_k - 1.0 / stress_temp_k)
    )
    voltage = (stress_voltage / use_voltage_v) ** voltage_exponent
    return np.asarray(thermal * voltage, dtype=float)


def equivalent_use_duration(durations: ArrayLike, factors: ArrayLike) -> NDArray[np.float64]:
    durations_array = np.asarray(durations, dtype=float)
    factors_array = np.asarray(factors, dtype=float)
    if durations_array.shape != factors_array.shape:
        raise ValueError("durations and acceleration factors must have matching shapes")
    if np.any(durations_array < 0) or np.any(factors_array <= 0):
        raise ValueError("durations must be nonnegative and factors must be positive")
    return durations_array * factors_array
