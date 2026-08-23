import numpy as np
from scipy.stats import norm

from hria.stats.lifetime import fit_weibull_censored
from hria.stats.multiple import benjamini_hochberg
from hria.stats.proportions import wilson_interval


def test_canary_rejects_normal_interval_mutation() -> None:
    wilson = wilson_interval(1, 10).confidence_interval
    p = 0.1
    radius = norm.ppf(0.975) * np.sqrt(p * (1 - p) / 10)
    broken_normal = (max(0.0, p - radius), min(1.0, p + radius))
    assert wilson != broken_normal
    assert wilson[0] > 0.0


def test_canary_rejects_ignore_censoring_mutation() -> None:
    rng = np.random.default_rng(4471)
    life = 2000 * rng.weibull(1.7, 10_000)
    observed = np.minimum(life, 900.0)
    events = life <= 900.0
    correct = fit_weibull_censored(observed, events)
    broken = fit_weibull_censored(observed[events], np.ones(events.sum(), dtype=bool))
    assert broken.eta < correct.eta * 0.65


def test_canary_rejects_missing_bh_mutation() -> None:
    p_values = np.array([0.01, 0.04, 0.03, 0.002])
    corrected = benjamini_hochberg(p_values)
    assert not np.allclose(corrected, p_values)
    assert corrected.tolist() == [0.02, 0.04, 0.04, 0.008]
