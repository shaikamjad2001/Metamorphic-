"""Order-independent weighted statistics and the Wilson score interval."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


def _sorted(values: np.ndarray, weights: np.ndarray, tiebreak: Optional[np.ndarray] = None):
    keys = (values,) if tiebreak is None else (tiebreak, values)
    order = np.lexsort(keys)
    return values[order], weights[order]


def weighted_quantile(values, weights, q: float) -> Optional[float]:
    """Lower weighted quantile: smallest v with cumulative weight >= q * total. Invariant to row order."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = ~np.isnan(v) & (w > 0)
    v, w = v[mask], w[mask]
    if v.size == 0:
        return None
    v, w = _sorted(v, w)
    cw = np.cumsum(w)
    idx = int(np.searchsorted(cw, q * cw[-1] - 1e-9 * cw[-1], side="left"))
    return float(v[min(idx, v.size - 1)])


def weighted_median(values, weights) -> Optional[float]:
    return weighted_quantile(values, weights, 0.5)


def bootstrap_weighted_medians(values, weights, rng: np.random.Generator, resamples: int) -> np.ndarray:
    """Resample records with replacement and return the weighted median of each resample.

    Records are put in a canonical content order (sorted by value, then weight) before resampling,
    so the result depends on the multiset of records and the seed, never on input row order.
    """
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = ~np.isnan(v) & (w > 0)
    v, w = v[mask], w[mask]
    n = v.size
    if n == 0:
        return np.array([])
    order = np.lexsort((w, v))
    v, w = v[order], w[order]
    idx = rng.integers(0, n, size=(resamples, n))
    counts = np.zeros((resamples, n))
    np.add.at(counts, (np.arange(resamples)[:, None], idx), 1.0)
    cw = np.cumsum(counts * w, axis=1)
    half = 0.5 * cw[:, -1:] - 1e-9 * cw[:, -1:]
    pos = np.argmax(cw >= half, axis=1)
    return v[pos]


def mad_outliers(values, k: float) -> np.ndarray:
    """Boolean mask of values farther than k scaled MADs from the median."""
    v = np.asarray(values, dtype=float)
    med = np.nanmedian(v)
    mad = 1.4826 * np.nanmedian(np.abs(v - med))
    if not np.isfinite(mad) or mad == 0:
        return np.zeros(v.shape, dtype=bool)
    return np.abs(v - med) > k * mad


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
