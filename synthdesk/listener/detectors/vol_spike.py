"""Price regime detectors."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

Event = Dict[str, Any]


def _timestamp(ts: Optional[str]) -> str:
    return ts or datetime.now(timezone.utc).isoformat()


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


__all__ = ["detect_vol_spike", "Event"]

