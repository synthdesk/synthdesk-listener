"""
Imbalance weight executor — regime-gated maker-side control primitive.

AUTHORITY:
  B-002-REGIME-SKEW-IMBALANCE-2026-01-29 (regime gating)
  B-003-SKEW-CALIBRATION-LINEAR-K07-2026-01-29 (size curve)
  B-004-INVENTORY-INTERACTION-ALPHA15-2026-01-29 (inventory amplification)
STATUS: Authorized for maker-side size modulation only.

Returns a continuous weight ∈ [0, 1] that indicates how strongly
imbalance opposes the maker's filled side. Higher weight = more
adverse pressure = reduce size / widen quote.

Usage:
    from synthdesk.listener.imbalance_weight import (
        imbalance_weight, classify_regime, size_mult, inventory_size_mult,
    )

    regime = classify_regime(spread_bps, activity, spread_median, activity_median)
    w = imbalance_weight(regime, imbalance, side, lag_ms)

    # Without inventory (B-003 only):
    mult = size_mult(w)

    # With inventory (B-004, full stack):
    mult = inventory_size_mult(w, inv_frac, side)
    quote_size *= mult

Regime law:
    - AUTHORIZED: tight_low, wide_low
    - FORBIDDEN:  tight_high, wide_high
    - Lag cutoff: 200ms (returns 0 beyond)

No tuning without a new court entry.
"""

from __future__ import annotations

# --- Frozen constants (B-002, B-003, B-004) ---
AUTHORIZED_REGIMES = frozenset({"tight_low", "wide_low"})
LAG_CUTOFF_MS = 200
SIZE_K = 0.7       # Linear size reduction coefficient (B-003)
INV_ALPHA = 1.5    # Inventory amplification exponent (B-004)
INV_DEADBAND = 0.05  # Below this |inv_frac|, no amplification (B-004)
MULT_FLOOR = 0.30  # Minimum multiplier — alive but cautious, never near-halt (B-004)


def classify_regime(
    spread_bps: float,
    activity: float,
    spread_median: float,
    activity_median: float,
) -> str:
    """
    Classify current market state into one of 4 regime cells.

    Args:
        spread_bps: Current spread in basis points.
        activity: Trades per second in trailing 1s window.
        spread_median: Run-global median spread_bps (computed once).
        activity_median: Run-global median activity (computed once).

    Returns:
        Regime string: "tight_low", "tight_high", "wide_low", or "wide_high".
    """
    s = "tight" if spread_bps <= spread_median else "wide"
    a = "low" if activity <= activity_median else "high"
    return f"{s}_{a}"


def imbalance_weight(
    regime: str,
    imbalance: float,
    side: int,
    lag_ms: float,
) -> float:
    """
    Compute maker-side control weight from imbalance.

    Args:
        regime: Current regime from classify_regime().
        imbalance: imbalance_top5 ∈ [-1, +1].
            Positive = bid-heavy (buying pressure).
            Negative = ask-heavy (selling pressure).
        side: Maker fill side. +1 = BUY, -1 = SELL.
        lag_ms: Time since observation in milliseconds.

    Returns:
        Weight ∈ [0, 1]. 0 = no action, 1 = maximum adverse pressure.

    Gating (B-002 frozen):
        - Returns 0 in forbidden regimes (tight_high, wide_high).
        - Returns 0 if lag_ms > 200.

    Semantics:
        - BUY side (side=+1): adverse when imbalance < 0 (selling pressure).
          weight = clamp(-imbalance, 0, 1)
        - SELL side (side=-1): adverse when imbalance > 0 (buying pressure).
          weight = clamp(+imbalance, 0, 1)
    """
    # Gate: forbidden regime
    if regime not in AUTHORIZED_REGIMES:
        return 0.0

    # Gate: stale observation
    if lag_ms > LAG_CUTOFF_MS:
        return 0.0

    # Adverse direction extraction
    if side == 1:
        # BUY fill: adverse when ask-heavy (imbalance < 0)
        raw = -imbalance
    elif side == -1:
        # SELL fill: adverse when bid-heavy (imbalance > 0)
        raw = imbalance
    else:
        return 0.0

    # Clamp to [0, 1]
    if raw <= 0.0:
        return 0.0
    if raw >= 1.0:
        return 1.0
    return raw


def size_mult(w: float) -> float:
    """
    Size reduction multiplier from imbalance weight.

    AUTHORITY: B-003-SKEW-CALIBRATION-LINEAR-K07-2026-01-29 (FROZEN)

    Curve: linear, k=0.7
        size_mult = clamp(1 - 0.7 * w, MULT_FLOOR, 1.0)

    Args:
        w: Weight from imbalance_weight(). Already 0 in forbidden regimes.

    Returns:
        Multiplier ∈ [MULT_FLOOR, 1.0]. Apply to quote size.
        1.0 = full size (no adverse pressure or forbidden regime).
        0.3 = minimum size (maximum adverse pressure, w=1.0).
    """
    m = 1.0 - SIZE_K * w
    if m < MULT_FLOOR:
        return MULT_FLOOR
    if m > 1.0:
        return 1.0
    return m


def inventory_size_mult(
    w: float,
    inv_frac: float,
    side: int,
) -> float:
    """
    Inventory-aware size multiplier (full control stack).

    AUTHORITY: B-004-INVENTORY-INTERACTION-ALPHA15-2026-01-29 (FROZEN)

    When the fill would worsen inventory (extend position in adverse direction),
    amplify the B-003 reduction by raising mult_base to a higher exponent:

        mult = max(MULT_FLOOR, mult_base ** (1 + α * inv_mag))

    When the fill would reduce/flatten inventory, apply B-003 only (no amplification).

    Args:
        w: Weight from imbalance_weight(). Already 0 in forbidden regimes/stale obs.
        inv_frac: Signed inventory fraction ∈ [-1, +1].
            clamp(inv_qty / inv_limit_qty, -1, 1). Caller computes this.
            Positive = long, negative = short.
        side: Maker fill side. +1 = BUY, -1 = SELL.

    Returns:
        Multiplier ∈ [MULT_FLOOR, 1.0]. Apply to quote size.
    """
    mult_base = size_mult(w)

    # If base mult is 1.0, no reduction to amplify
    if mult_base >= 1.0:
        return 1.0

    # Would this fill worsen inventory?
    would_worsen = (side == 1 and inv_frac > 0) or (side == -1 and inv_frac < 0)

    if not would_worsen:
        return mult_base

    # Inventory magnitude (with deadband)
    inv_mag = abs(inv_frac)
    if inv_mag < INV_DEADBAND:
        return mult_base

    # Amplify: mult_base^(1 + α * inv_mag)
    # mult_base < 1, exponent > 1 → result is smaller (more reduction)
    exponent = 1.0 + INV_ALPHA * inv_mag
    m = mult_base ** exponent

    return max(MULT_FLOOR, m)
