"""Price regime detectors."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

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


__all__ = ["detect_breakout", "Event"]

