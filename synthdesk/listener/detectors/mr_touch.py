"""Price regime detectors."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..transforms import mean_reversion_bands

Event = Dict[str, Any]


def _timestamp(ts: Optional[str]) -> str:
    return ts or datetime.now(timezone.utc).isoformat()


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


__all__ = ["detect_mr_touch", "Event"]

