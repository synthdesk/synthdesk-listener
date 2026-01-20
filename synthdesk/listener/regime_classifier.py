"""
Regime classification logic with frozen thresholds.

This module is the authoritative source for:
- RegimeThresholds dataclass (V1 legacy + V2 z-space)
- REGIME_THRESHOLDS_V2 canonical z-space thresholds
- classify_regime() production entry point
- ClassificationResult with full decision audit trail

Both replay.py and the live listener import from here.

IMPORTANT: V2 operates in z-space (normalized returns). The classifier
expects z_mean and z_std as inputs, NOT raw returns_mean/returns_std.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# ---------------------------
# Regime Thresholds (Frozen)
# ---------------------------

@dataclass(frozen=True)
class RegimeThresholds:
    """
    Frozen regime classification thresholds with calibration metadata.

    V2: Thresholds are now DIMENSIONLESS (z-space).
    - z_drift_threshold: threshold on |z_mean| (normalized drift)
    - z_high_vol_threshold: threshold on z_std (should hover ~1 normally)
    - z_breakout_mult: multiplier for breakout detection

    These thresholds apply uniformly across ALL symbols because
    inputs are already normalized by per-symbol EWMA volatility.
    """

    # Core thresholds (z-space, dimensionless)
    z_drift_threshold: float
    z_high_vol_threshold: float
    z_breakout_mult: float

    # Window binding (thresholds are only valid for this window)
    window_ticks: int

    # Calibration metadata (frozen, for auditability)
    calibration_window: str
    calibration_date: str
    drift_percentile: str
    high_vol_percentile: str
    sample_count: int
    notes: str = ""

    # Version identifier for payload tagging
    @property
    def thresholds_id(self) -> str:
        return f"regime_thresholds_v2_{self.calibration_date}"

    # Legacy compatibility: map old field names to z-space equivalents
    @property
    def drift_threshold(self) -> float:
        return self.z_drift_threshold

    @property
    def high_vol_threshold(self) -> float:
        return self.z_high_vol_threshold

    @property
    def breakout_mult(self) -> float:
        return self.z_breakout_mult


# =============================================================================
# V2 Z-Space Thresholds (Frozen)
# =============================================================================
# These thresholds operate on NORMALIZED returns (z-space).
# They are dimensionless and apply uniformly across all symbols.
#
# Semantic meaning:
# - z_drift_threshold: avg z-return magnitude indicating directional bias
# - z_high_vol_threshold: realized z-std above which market is "abnormally volatile"
#   (in a well-behaved market, z_std should hover around 1.0)
# - z_breakout_mult: how many z-stds a move must exceed to be "breakout"
#
# These are INITIAL values. Calibration against multi-symbol data will refine.
# =============================================================================
REGIME_THRESHOLDS_V2 = RegimeThresholds(
    z_drift_threshold=0.15,      # ~0.15σ average drift over window
    z_high_vol_threshold=1.5,    # realized vol 50% above baseline
    z_breakout_mult=2.5,         # same multiplier semantics as V1
    window_ticks=60,
    calibration_window="initial z-space calibration",
    calibration_date="2026-01-12",
    drift_percentile="0.15σ (initial estimate)",
    high_vol_percentile="1.5σ (initial estimate)",
    sample_count=0,
    notes="V2: z-space thresholds, dimensionless, uniform across symbols",
)

# Legacy V1 thresholds (deprecated, kept for reference)
REGIME_THRESHOLDS_V1 = RegimeThresholds(
    z_drift_threshold=0.00002,   # was raw returns_mean
    z_high_vol_threshold=0.00020,  # was raw returns_std
    z_breakout_mult=2.5,
    window_ticks=60,
    calibration_window="2025-12-30 to 2026-01-10",
    calibration_date="2026-01-10",
    drift_percentile="p75 of |returns_mean| (~0.000019, rounded up)",
    high_vol_percentile="p90 of returns_std (~0.00018, rounded up)",
    sample_count=5775,
    notes="DEPRECATED: V1 raw-space thresholds, do not use with z-space inputs",
)

# Drift persistence gate (H-005B). Keep minimal and auditable.
DRIFT_PERSIST_LOOKBACK = 2


# ---------------------------
# Classification Result
# ---------------------------

@dataclass(frozen=True)
class RegimeScores:
    """
    Per-regime membership scores (all in same direction: higher = more that regime).

    This unifies confidence semantics: for ALL regimes including chop,
    a higher score means "more confident this IS the regime".
    """
    chop: float
    drift: float
    high_vol: float
    breakout: float

    def max_score(self) -> Tuple[str, float]:
        """Return (regime, score) for the highest-scoring regime."""
        scores = [
            ("chop", self.chop),
            ("drift", self.drift),
            ("high_vol", self.high_vol),
            ("breakout", self.breakout),
        ]
        return max(scores, key=lambda x: x[1])


@dataclass(frozen=True)
class ClassificationResult:
    """
    Full classification result with audit trail.

    Contains:
    - regime: the chosen regime label
    - confidence: membership strength for the chosen regime (unified semantics)
    - scores: per-regime scores for debugging
    - metrics: the input metrics used for classification
    - thresholds_id: which threshold set was used
    """
    regime: str
    confidence: float
    scores: RegimeScores
    metrics: Dict[str, float]
    thresholds_id: str

    def to_payload_metrics(self) -> Dict[str, Any]:
        """Return minimal metrics dict for spine event payload."""
        return {
            "z_mean": self.metrics.get("z_mean"),
            "z_std": self.metrics.get("z_std"),
            "ewma_sigma": self.metrics.get("ewma_sigma"),
            # Legacy fields (deprecated)
            "returns_mean": self.metrics.get("returns_mean"),
            "returns_std": self.metrics.get("returns_std"),
            "range_pct": self.metrics.get("range_pct"),
        }

    def to_debug_payload(self) -> Dict[str, Any]:
        """Return full debug payload for diagnostics."""
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "thresholds_id": self.thresholds_id,
            "metrics": self.metrics,
            "scores": {
                "chop": self.scores.chop,
                "drift": self.scores.drift,
                "high_vol": self.scores.high_vol,
                "breakout": self.scores.breakout,
            },
        }


# ---------------------------
# Helpers
# ---------------------------

def _quantize_confidence(confidence: float) -> float:
    """
    Quantize confidence to 6 decimal places to prevent floating-point drift.
    This ensures deterministic replay by eliminating accumulation errors.
    """
    return round(confidence, 6)


def _as_float(value: object) -> Optional[float]:
    """Safely convert value to float, rejecting bools and None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _drift_persist_ok(
    z_mean_history: Optional[object],
    drift_threshold: float,
    lookback: int,
) -> bool:
    """Return True if recent z_mean values show persistent drift."""
    if lookback < 1:
        return False
    if not isinstance(z_mean_history, list):
        return False
    if len(z_mean_history) < lookback + 1:
        return False
    recent = z_mean_history[-(lookback + 1):]
    values: list[float] = []
    for value in recent:
        val = _as_float(value)
        if val is None:
            return False
        values.append(val)
    if any(v == 0.0 for v in values):
        return False
    sign = 1.0 if values[0] > 0.0 else -1.0
    if not all((v > 0.0) == (sign > 0.0) for v in values):
        return False
    mean_abs = sum(abs(v) for v in values) / len(values)
    return mean_abs >= drift_threshold


# ---------------------------
# Core Classification Logic
# ---------------------------

def classify_regime_full(
    symbol: str,
    metrics: dict,
    ts: float,
    thresholds: RegimeThresholds,
) -> ClassificationResult:
    """
    Classify market regime from z-space metrics using frozen thresholds.

    V2: Expects z-space inputs (z_mean, z_std) from per-symbol normalized returns.
    Thresholds are dimensionless and apply uniformly across all symbols.

    Returns a full ClassificationResult with:
    - regime label
    - unified confidence (higher = more confident in chosen regime)
    - per-regime scores
    - input metrics for audit

    Args:
        symbol: Symbol identifier (unused but kept for interface compatibility)
        metrics: Dict with z_mean, z_std (PRIMARY) or returns_mean, returns_std (LEGACY)
        ts: Timestamp (unused but kept for interface compatibility)
        thresholds: Frozen RegimeThresholds instance (V2 z-space)

    Returns:
        ClassificationResult with full decision audit trail
    """
    # Default for invalid input
    default_scores = RegimeScores(chop=1.0, drift=0.0, high_vol=0.0, breakout=0.0)
    default_metrics: Dict[str, float] = {}

    if not isinstance(metrics, dict):
        return ClassificationResult(
            regime="chop",
            confidence=0.0,
            scores=default_scores,
            metrics=default_metrics,
            thresholds_id=thresholds.thresholds_id,
        )

    # =================================================================
    # Z-Space Metrics (PRIMARY) - normalized by per-symbol EWMA σ
    # =================================================================
    z_mean = _as_float(metrics.get("z_mean"))
    z_std = _as_float(metrics.get("z_std"))
    ewma_sigma = _as_float(metrics.get("ewma_sigma"))

    # Legacy fallback: if z-space not available, use raw metrics
    # This allows backwards compatibility during transition
    if z_mean is None or z_std is None:
        returns_mean = _as_float(metrics.get("returns_mean"))
        returns_std = _as_float(metrics.get("returns_std"))
        # Use raw metrics with V1 interpretation (not recommended)
        z_mean = returns_mean
        z_std = returns_std

    # Build metrics dict for audit
    input_metrics: Dict[str, float] = {}
    if z_mean is not None:
        input_metrics["z_mean"] = z_mean
    if z_std is not None:
        input_metrics["z_std"] = z_std
    if ewma_sigma is not None:
        input_metrics["ewma_sigma"] = ewma_sigma
    # Also capture legacy fields if present
    for key in ("returns_mean", "returns_std", "range_pct"):
        val = _as_float(metrics.get(key))
        if val is not None:
            input_metrics[key] = val

    if z_mean is None and z_std is None:
        return ClassificationResult(
            regime="chop",
            confidence=0.0,
            scores=default_scores,
            metrics=input_metrics,
            thresholds_id=thresholds.thresholds_id,
        )

    # =================================================================
    # Z-Space Classification (dimensionless thresholds)
    # =================================================================
    # In z-space:
    # - z_mean: average normalized return (drift signal)
    # - z_std: realized volatility relative to EWMA baseline (should hover ~1)
    #
    # Thresholds:
    # - z_high_vol_threshold: z_std above which = "abnormally volatile"
    # - z_drift_threshold: |z_mean| above which = "directional bias"
    # - z_breakout_mult: |z_mean| / z_std above which = "breakout"
    # =================================================================

    high_vol_threshold = thresholds.z_high_vol_threshold
    drift_threshold = thresholds.z_drift_threshold
    breakout_mult = thresholds.z_breakout_mult

    abs_z_mean = abs(z_mean) if z_mean is not None else 0.0
    z_std_value = z_std if z_std is not None else 0.0

    # Compute proximity scores (0 = far from threshold, 1 = at/past threshold)
    vol_prox = z_std_value / high_vol_threshold if z_std is not None and high_vol_threshold > 0 else 0.0
    drift_prox = abs_z_mean / drift_threshold if z_mean is not None and drift_threshold > 0 else 0.0
    breakout_prox = (
        abs_z_mean / (breakout_mult * z_std_value)
        if z_mean is not None and z_std is not None and z_std_value > 0.0
        else 0.0
    )

    # Clip proximities to [0, 2] range (allow overshoot for confidence)
    vol_prox = max(0.0, min(2.0, vol_prox))
    drift_prox = max(0.0, min(2.0, drift_prox))
    breakout_prox = max(0.0, min(2.0, breakout_prox))

    # Convert proximities to regime scores (unified semantics)
    high_vol_score = vol_prox / 2.0 if vol_prox <= 1.0 else 0.5 + (vol_prox - 1.0) / 2.0
    drift_score = drift_prox / 2.0 if drift_prox <= 1.0 else 0.5 + (drift_prox - 1.0) / 2.0
    breakout_score = breakout_prox / 2.0 if breakout_prox <= 1.0 else 0.5 + (breakout_prox - 1.0) / 2.0

    # Chop score: inverse of max non-chop proximity
    max_non_chop_prox = max(vol_prox, drift_prox, breakout_prox)
    chop_score = 1.0 - min(1.0, max_non_chop_prox)

    # Quantize scores
    scores = RegimeScores(
        chop=_quantize_confidence(chop_score),
        drift=_quantize_confidence(drift_score),
        high_vol=_quantize_confidence(high_vol_score),
        breakout=_quantize_confidence(breakout_score),
    )

    # =================================================================
    # Regime Decision (priority: high_vol > breakout > drift > chop)
    # =================================================================
    is_high_vol = z_std is not None and z_std_value > high_vol_threshold
    is_breakout = (
        z_mean is not None
        and z_std is not None
        and z_std_value > 0.0
        and abs_z_mean > breakout_mult * z_std_value
    )
    is_drift = z_mean is not None and abs_z_mean > drift_threshold
    persist_ok = False
    if is_drift:
        persist_ok = _drift_persist_ok(
            metrics.get("z_mean_history"),
            drift_threshold,
            DRIFT_PERSIST_LOOKBACK,
        )

    if is_high_vol:
        confidence = min(1.0, (z_std_value - high_vol_threshold) / high_vol_threshold)
        return ClassificationResult(
            regime="high_vol",
            confidence=_quantize_confidence(confidence),
            scores=scores,
            metrics=input_metrics,
            thresholds_id=thresholds.thresholds_id,
        )

    if is_breakout:
        confidence = min(1.0, (abs_z_mean - breakout_mult * z_std_value) / (breakout_mult * z_std_value))
        return ClassificationResult(
            regime="breakout",
            confidence=_quantize_confidence(confidence),
            scores=scores,
            metrics=input_metrics,
            thresholds_id=thresholds.thresholds_id,
        )

    if is_drift:
        confidence = min(1.0, (abs_z_mean - drift_threshold) / drift_threshold)
        return ClassificationResult(
            regime="drift_persist" if persist_ok else "drift",
            confidence=_quantize_confidence(confidence),
            scores=scores,
            metrics=input_metrics,
            thresholds_id=thresholds.thresholds_id,
        )

    # Chop: confidence is how far from escaping
    confidence = chop_score
    return ClassificationResult(
        regime="chop",
        confidence=_quantize_confidence(confidence),
        scores=scores,
        metrics=input_metrics,
        thresholds_id=thresholds.thresholds_id,
    )


def classify_regime(
    symbol: str,
    metrics: dict,
    ts: float,
    thresholds: Optional[RegimeThresholds] = None,
) -> tuple[str, float]:
    """
    Classify market regime using canonical frozen thresholds.

    This is the production entry point. Uses REGIME_THRESHOLDS_V2 by default.

    For full audit trail, use classify_regime_full() instead.

    Args:
        symbol: Symbol identifier
        metrics: Dict with z_mean, z_std (V2) or returns_mean, returns_std (V1 legacy)
        ts: Timestamp
        thresholds: Optional custom thresholds (defaults to REGIME_THRESHOLDS_V2)

    Returns:
        (regime_label, confidence) tuple
    """
    if thresholds is None:
        thresholds = REGIME_THRESHOLDS_V2
    result = classify_regime_full(symbol, metrics, ts, thresholds)
    return result.regime, result.confidence


def validate_window_config(config_window: int, thresholds: RegimeThresholds) -> None:
    """
    Validate that config window matches threshold calibration.

    Raises ConfigError if mismatch detected.
    """
    if config_window != thresholds.window_ticks:
        raise ValueError(
            f"Window mismatch: config has {config_window} ticks, "
            f"but thresholds were calibrated for {thresholds.window_ticks} ticks. "
            f"Using mismatched windows invalidates regime classification."
        )


__all__ = [
    "RegimeThresholds",
    "RegimeScores",
    "ClassificationResult",
    "REGIME_THRESHOLDS_V1",
    "REGIME_THRESHOLDS_V2",
    "classify_regime",
    "classify_regime_full",
    "validate_window_config",
]
