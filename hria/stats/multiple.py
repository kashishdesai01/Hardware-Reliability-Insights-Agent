from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def benjamini_hochberg(p_values: ArrayLike) -> NDArray[np.float64]:
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1 or np.any((values < 0) | (values > 1)):
        raise ValueError("p-values must be a one-dimensional array in [0, 1]")
    count = len(values)
    if count == 0:
        return values.copy()
    order = np.argsort(values)
    ranked = values[order]
    adjusted = ranked * count / np.arange(1, count + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty(count, dtype=float)
    result[order] = np.minimum(adjusted, 1.0)
    return result
