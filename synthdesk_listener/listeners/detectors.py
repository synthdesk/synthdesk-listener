"""Price regime detectors."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .transforms import mean_reversion_bands


Event = Dict[str, Any]


def _timestamp(ts: Optional[str]) -> str:
    return ts or datetime.now(timezone.utc).isoformat()


def detect_breakout(
    pair: str,
    price: float,
    rolling_mean: float,
    breakout_threshold: float,
    timestamp: Optional[str] = None,
) -> Optional[Event]:
    """Detect when price deviates from rolling mean beyond the threshold (relative).

    breakout_threshold is interpreted as a fractional distance from the mean.
    """
    ts = _timestamp(timestamp)
    if rolling_mean == 0:
        return None
    deviation = price - rolling_mean
    deviation_pct = deviation / rolling_mean
    if abs(deviation_pct) <= breakout_threshold:
        return None

    return {
        "event": "breakout",
        "pair": pair,
        "price": price,
        "timestamp": ts,
        "metrics": {
            "rolling_mean": rolling_mean,
            "deviation": deviation,
            "deviation_pct": deviation_pct,
            "breakout_threshold": breakout_threshold,
        },
        "version": None,
    }


def detect_vol_spike(
    pair: str,
    short_vol: float,
    long_vol: float,
    timestamp: Optional[str] = None,
) -> Optional[Event]:
    """Detect when short-term volatility exceeds the long-term baseline."""
    ts = _timestamp(timestamp)
    if long_vol <= 0:
        return None
    if short_vol <= long_vol:
        return None

    return {
        "event": "vol_spike",
        "pair": pair,
        "price": None,
        "timestamp": ts,
        "metrics": {
            "short_vol": short_vol,
            "long_vol": long_vol,
            "ratio": short_vol / long_vol if long_vol else 0.0,
        },
        "version": None,
    }


def detect_mr_touch(
    pair: str,
    price: float,
    rolling_mean: float,
    band_width: float,
    timestamp: Optional[str] = None,
) -> Optional[Event]:
    """Detect when price touches mean-reversion bands."""
    ts = _timestamp(timestamp)
    lower, upper = mean_reversion_bands(rolling_mean, band_width)
    if lower <= price <= upper:
        return None

    position = "upper" if price > upper else "lower"
    return {
        "event": "mr_touch",
        "pair": pair,
        "price": price,
        "timestamp": ts,
        "metrics": {
            "rolling_mean": rolling_mean,
            "band_width": band_width,
            "lower_band": lower,
            "upper_band": upper,
            "position": position,
        },
        "version": None,
    }


__all__ = ["detect_breakout", "detect_vol_spike", "detect_mr_touch", "Event"]
