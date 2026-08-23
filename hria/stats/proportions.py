from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from scipy.stats import norm


@dataclass(frozen=True)
class ProportionEstimate:
    successes: int
    total: int
    proportion: float
    confidence_interval: tuple[float, float]
    method: str = "wilson"


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> ProportionEstimate:
    if total <= 0:
        raise ValueError("total must be positive")
    if not 0 <= successes <= total:
        raise ValueError("successes must be between zero and total")
    z_value = float(norm.ppf(0.5 + confidence / 2.0))
    proportion = successes / total
    denominator = 1 + z_value**2 / total
    center = (proportion + z_value**2 / (2 * total)) / denominator
    radius = (
        z_value
        * sqrt(proportion * (1 - proportion) / total + z_value**2 / (4 * total**2))
        / denominator
    )
    return ProportionEstimate(
        successes=successes,
        total=total,
        proportion=proportion,
        confidence_interval=(max(0.0, center - radius), min(1.0, center + radius)),
    )
