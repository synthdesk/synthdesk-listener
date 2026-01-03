"""Invariant validation helpers for listener checks."""

from __future__ import annotations

import math
from typing import Any, Dict


def is_finite_float(value: Any) -> bool:
    """Check if value is a finite float (not NaN, Inf, or None)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return math.isfinite(float(value))


def validate_metrics(metrics: Dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate metrics dict for invalid values (NaN, Inf, None).
    
    Returns:
        (is_valid, list_of_invalid_fields)
    """
    invalid_fields: list[str] = []
    
    if not isinstance(metrics, dict):
        return False, ["metrics is not a dict"]
    
    required_fields = ["log_return", "rolling_mean", "rolling_std", "zscore", "slope", "range"]
    for field in required_fields:
        value = metrics.get(field)
        if value is not None and not is_finite_float(value):
            invalid_fields.append(field)
    
    return len(invalid_fields) == 0, invalid_fields


def validate_confidence(confidence: float) -> bool:
    """Check if confidence is in valid bounds [0.0, 1.0]."""
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return False
    conf_float = float(confidence)
    return 0.0 <= conf_float <= 1.0 and math.isfinite(conf_float)


def validate_regime(regime: str) -> bool:
    """Check if regime is in valid REGIMES set."""
    from synthdesk.listener.regime_classifier import REGIMES
    return isinstance(regime, str) and regime in REGIMES

