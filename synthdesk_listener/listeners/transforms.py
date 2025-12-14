"""Transform utilities for rolling statistics and price-derived metrics."""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple


def rolling_mean(values: Sequence[float], window: int) -> float:
    """Compute the mean over the last `window` values (or fewer if not available)."""
    if window <= 0:
        raise ValueError("window must be positive")
    if not values:
        return 0.0
    slice_values = values[-window:]
    return sum(slice_values) / len(slice_values)


def rolling_std(values: Sequence[float], window: int) -> float:
    """Compute the sample standard deviation over the last `window` values."""
    if window <= 0:
        raise ValueError("window must be positive")
    if not values:
        return 0.0
    slice_values = values[-window:]
    n = len(slice_values)
    if n < 2:
        return 0.0
    mean = sum(slice_values) / n
    variance = sum((v - mean) ** 2 for v in slice_values) / (n - 1)
    return math.sqrt(variance)


def percentage_change(previous: float, current: float) -> float:
    """Return percentage change between two prices."""
    if previous == 0:
        raise ValueError("previous price cannot be zero for percentage change")
    return (current - previous) / previous


def percent_change(previous: float, current: float) -> float:
    """Alias for `percentage_change` (fractional change, not multiplied by 100)."""
    return percentage_change(previous, current)


def rolling_volatility(prices: Sequence[float], window: int) -> float:
    """Estimate volatility as std dev of percentage changes over a rolling window of prices."""
    if window <= 1:
        raise ValueError("window must be greater than 1")
    if len(prices) < 2:
        return 0.0
    window_prices = prices[-window:]
    if len(window_prices) < 2:
        return 0.0
    pct_changes = [percentage_change(a, b) for a, b in zip(window_prices[:-1], window_prices[1:]) if a != 0]
    if len(pct_changes) < 2:
        return 0.0
    return rolling_std(pct_changes, len(pct_changes))


def mean_reversion_bands(mean: float, band_width: float) -> Tuple[float, float]:
    """Return lower/upper mean-reversion bands using a fractional band width."""
    if band_width < 0:
        raise ValueError("band_width must be non-negative")
    return mean * (1 - band_width), mean * (1 + band_width)


__all__ = [
    "rolling_volatility",
    "rolling_mean",
    "rolling_std",
    "mean_reversion_bands",
    "percentage_change",
    "percent_change",
]
