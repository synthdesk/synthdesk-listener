"""Transform utilities for rolling statistics and price-derived metrics."""

from __future__ import annotations

import math
from typing import Sequence, Tuple


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


def log_return(previous: float, current: float) -> float:
    """Return the log return ln(current / previous)."""
    if previous <= 0 or current <= 0:
        raise ValueError("prices must be positive for log returns")
    return math.log(current / previous)


def log_returns(prices: Sequence[float], window: int) -> list[float]:
    """Return the last `window` log returns computed from `prices`."""
    if window <= 0:
        raise ValueError("window must be positive")
    if len(prices) < 2:
        return []

    # To compute `window` returns, we need `window + 1` prices.
    n_returns = min(window, len(prices) - 1)
    slice_prices = prices[-(n_returns + 1) :]

    returns: list[float] = []
    for prev, cur in zip(slice_prices[:-1], slice_prices[1:]):
        if prev <= 0 or cur <= 0:
            continue
        returns.append(log_return(prev, cur))
    return returns


def zscore(x: float, mean: float, std: float) -> float:
    """Compute a z-score (x - mean) / std with a zero-std guard."""
    if std == 0:
        return 0.0
    return (x - mean) / std


def slope(prices: Sequence[float], n: int) -> float:
    """Compute the simple slope (p_t - p_{t-n}) / n over the last n steps."""
    if n <= 0:
        raise ValueError("n must be positive")
    if len(prices) <= n:
        return 0.0
    current = prices[-1]
    past = prices[-(n + 1)]
    return (current - past) / n


def price_range(prices: Sequence[float], window: int) -> float:
    """Compute max(prices) - min(prices) over the last `window` prices."""
    if window <= 0:
        raise ValueError("window must be positive")
    if not prices:
        return 0.0
    slice_prices = prices[-window:]
    return max(slice_prices) - min(slice_prices)


def pearson_corr(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute Pearson correlation for two equal-length series."""
    if len(a) != len(b):
        raise ValueError("series must have equal length")
    n = len(a)
    if n < 2:
        return 0.0

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    cov = 0.0
    var_a = 0.0
    var_b = 0.0
    for x, y in zip(a, b):
        da = x - mean_a
        db = y - mean_b
        cov += da * db
        var_a += da * da
        var_b += db * db

    if var_a == 0 or var_b == 0:
        return 0.0
    return cov / math.sqrt(var_a * var_b)


def rolling_corr(a: Sequence[float], b: Sequence[float], window: int) -> float:
    """Compute correlation over the last `window` aligned observations."""
    if window <= 0:
        raise ValueError("window must be positive")
    n = min(window, len(a), len(b))
    if n < 2:
        return 0.0
    return pearson_corr(a[-n:], b[-n:])


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
    "log_return",
    "log_returns",
    "pearson_corr",
    "price_range",
    "rolling_corr",
    "rolling_volatility",
    "rolling_mean",
    "rolling_std",
    "slope",
    "mean_reversion_bands",
    "percentage_change",
    "percent_change",
    "zscore",
]
