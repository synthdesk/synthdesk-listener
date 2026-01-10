STATUS: LAW (normative, constraining)
VIOLATION CONSEQUENCE: Non-compliant emissions must be rejected or reverted.

# Level 0: Measurement Hygiene Law

## Objective

Ensure every later statistic is trustworthy by guaranteeing:
1. **Temporal Integrity**: Time is sane (monotonic, gap-aware).
2. **Numeric Determinism**: Numbers are sane (bit-identical replay).
3. **Sampling Integrity**: Windows are sane (explicit rules for partial/gapped data).

**Promise**: If two observers replay the same raw events, they will agree on what happened.

---

## Pillar 1: Temporal Integrity

### 1.1 Timestamp Monotonicity (Normative)

**Rule**: Per-pair timestamps MUST be strictly increasing.

**Implementation**:
- Each pair maintains `last_timestamp`.
- If `timestamp_current <= last_timestamp`: the tick is **invalid** and MUST be:
  - Logged to `sequence_integrity.log` with: `timestamp, pair, tick_id, violation="non_monotonic", previous_timestamp`
  - Skipped (not processed, not written to tick_log.csv)
- Valid ticks update `last_timestamp` for that pair.

**Replay Stability**:
- Two runs with identical input prices MUST produce identical monotonicity violations in `sequence_integrity.log`.
- Violation logging is part of the deterministic replay surface.

**Rationale**: Non-monotonic timestamps indicate data corruption, clock skew, or replay errors. They MUST NOT silently corrupt windows or statistics.

---

### 1.2 Gap Detection and Accounting

**Definition of a Gap**:
- A gap occurs when `timestamp_current - last_timestamp > gap_threshold`.
- Default `gap_threshold = poll_interval * 2.5` (e.g., 2.5 seconds for 1-second polling).
- Gap threshold MUST be configurable and MUST be logged in run metadata.

**Gap Logging**:
- Gaps MUST be logged to `sequence_integrity.log` with:
  ```
  timestamp_current, pair, tick_id, violation="gap", duration_seconds, last_timestamp
  ```
- Gaps are **observable events**, not errors. They indicate missing data.

**Gap Semantics for Windows**:
- **Gaps do NOT invalidate windows** (windows are tick-count based, not time-based).
- Windows operate on the ticks that exist, ignoring wall-clock gaps.
- **However**: If a gap spans multiple ticks (e.g., exchange outage), the window will reflect whatever ticks were actually observed.

**Gap Metadata Emission**:
- Each tick emitted to `tick_log.csv` MUST include:
  - `gap_since_last`: integer seconds since last tick (0 if no gap, >0 if gap detected).
- This allows downstream systems to interpret windows correctly.

**Replay Stability**:
- Gap detection MUST be deterministic given identical input timestamps.
- Two runs MUST produce identical `gap_since_last` values.

**Rationale**: Gaps are reality. Level 0 requires we observe them honestly and make them visible, not hide them.

---

## Pillar 2: Numeric Determinism

### 2.1 Quantization Rule

### 2.2 Internal Computation
- All internal statistics use standard `float` arithmetic.
- Rolling windows, means, variances, log returns computed as `float`.

### 2.3 Emission Boundary (The Gate)
- **No raw floats may cross the listener boundary.**
- All scalar metrics are quantized to fixed-point integers at emission time.
- Quantization function:
  ```python
  import math

  def quantize(x: float, scale: int) -> int:
      """Deterministic quantization with explicit rounding rule."""
      if x >= 0:
          return int(math.floor(x * scale + 0.5))
      else:
          return -int(math.floor(abs(x) * scale + 0.5))
  ```
- **Rounding mode**: Round-half-away-from-zero (explicit floor-based).
- Rationale: Avoids Python's round-half-to-even surprise; explicit floor-based rounding is simpler to verify.

### 2.4 Quantization Scales

**Rationale**: Scales chosen to ensure ≥1 integer LSB movement under typical 1s BTC tick dynamics while keeping values within 32-bit int bounds.

| Metric                | Scale  | Example: 0.00123 → |
|-----------------------|--------|-------------------|
| `log_return`          | `1e5`  | `123`             |
| `realized_vol`        | `1e5`  | `123`             |
| `rolling_mean`        | `1e5`  | `123`             |
| `rolling_std`         | `1e5`  | `123`             |
| `zscore`              | `1e4`  | `12`              |
| `slope`               | `1e5`  | `123`             |
| `range`               | `1e5`  | `123`             |
| `kurtosis_excess`     | `1e4`  | `12`              |
| `tail_ratio`          | `1e4`  | `12`              |
| `vol_q33`             | `1e5`  | `123`             |
| `vol_q66`             | `1e5`  | `123`             |

### 2.5 Storage & Spine
- All emitted metrics stored as **integers**, **string enums**, or **null** in JSON/CSV.
- Event spine (`.jsonl`) contains only: `int`, `str` (for enums like `vol_bucket`), or `null`.
- `tick_log.csv` contains only quantized integers (or empty cells for null).
- **No floats** are written to disk by the listener.

### 2.6 Presentation Layer (Downstream Only)
- If human-readable floats are needed, downstream systems convert:
  ```python
  float_value = int_value / scale
  ```
- The listener itself never emits this conversion.

### 2.7 Numeric Invariants

1. **No floats in emitted artifacts**: All `metrics` dicts contain only `int`, `str` (enum), or `null` values.
2. **Deterministic quantization**: Quantize uses the explicit rule `int(math.floor(x*scale + 0.5))` for `x ≥ 0` and `-int(math.floor(abs(x)*scale + 0.5))` for `x < 0`. Python's default `round()` is **not used** (to avoid round-half-to-even surprises).
3. **Scale is immutable**: Once a metric's scale is chosen, it cannot change without a major version bump.
4. **Canonicalization**: Per-tick `log_return` is quantized **immediately** to `log_return_int`. All rolling statistics MUST be computed from the integer series (or floats derived solely from that integer series), not from raw float returns.

---

## Pillar 3: Sampling Integrity

### 3.1 Window Sampling Rules

**Windows are tick-count based**, not wall-clock based. A window of size `W` contains the last `W` **valid ticks** (ticks that passed monotonicity checks).

**Startup Behavior (Partial Windows)**:
- If the rolling history contains fewer than `W` ticks:
  - Use `effective_W = min(W, len(history))`.
  - Emit `actual_window_size` metadata in tick_log.csv for that tick.
  - If `effective_W < minimum_required` for a statistic (e.g., `W < 2` for volatility), emit `null` for that statistic.

**Gap-Inside-Window Behavior**:
- Gaps (as defined in §1.2) do **not** invalidate windows.
- Windows operate on whatever ticks exist, regardless of wall-clock gaps.
- **However**: If a window spans a large gap, the `gap_since_last` metadata makes this observable downstream.

**Restart Boundaries**:
- Windows resume from persisted state (`state_<PAIR>.json`).
- No interpolation or synthetic ticks across restart boundaries.
- First tick after restart uses `effective_W = len(reloaded_history)`.

**Window Integrity Rule**:
- A window is valid if it contains at least `minimum_required` **valid** ticks for the statistic being computed.
- Invalid windows emit `null` for dependent statistics.

**Metadata Requirements**:
- Every tick MUST emit:
  - `actual_window_size`: number of ticks actually used in the window (≤ W).
  - `gap_since_last`: seconds since last tick (from §1.2).

### 3.2 Sampling Invariants

1. **No synthetic ticks**: The listener MUST NOT create, interpolate, or forward-fill missing ticks.
2. **No cross-gap healing**: Windows do not "heal" or "reconnect" across gaps; they simply use the ticks that exist.
3. **Deterministic sampling**: Two runs with identical valid ticks MUST produce identical windows (same ticks, same order).

---

## Level 0 Completion Criteria

Level 0 is **complete** when all three pillars are satisfied:

1. ✅ **Temporal Integrity**:
   - Monotonicity violations are logged and skipped deterministically.
   - Gaps are detected, logged, and exposed via metadata.

2. ✅ **Numeric Determinism**:
   - All emitted scalars are quantized integers.
   - Replay produces byte-identical `tick_log.csv` and event spine.

3. ✅ **Sampling Integrity**:
   - Window rules are explicit and deterministic.
   - Partial windows and gaps are handled with documented semantics.
   - Metadata exposes window size and gap duration.

**Test**: Two observers replaying the same raw price stream MUST agree on:
- Which ticks were valid/invalid (monotonicity)
- Where gaps occurred (gap_since_last)
- What statistics were computed (including nulls for invalid windows)
- The exact integer values of all emitted metrics

---

## Replay Verification Criterion

A listener deployment passes level 0 if:

```bash
# Run 1
python synthdesk_listener/main.py --config config.json
sha256sum runs/0.5.0/2026-01-05/tick_log.csv > hash1_tick.txt
sha256sum runs/0.5.0/2026-01-05/sequence_integrity.log > hash1_seq.txt

# Run 2 (replay)
rm -rf runs/0.5.0/2026-01-05/
python synthdesk_listener/main.py --config config.json
sha256sum runs/0.5.0/2026-01-05/tick_log.csv > hash2_tick.txt
sha256sum runs/0.5.0/2026-01-05/sequence_integrity.log > hash2_seq.txt

# Verify
diff hash1_tick.txt hash2_tick.txt  # MUST be empty
diff hash1_seq.txt hash2_seq.txt    # MUST be empty
```

All three pillars (temporal, numeric, sampling) MUST produce byte-identical outputs.

## Implementation Notes

### Temporal
- Monotonicity checks in `PriceListener.process_tick()` before any metric computation.
- Gap detection uses `timestamp_current - last_timestamp` compared to `gap_threshold` from config.
- `gap_since_last` computed and emitted as integer seconds in tick_log.csv.

### Numeric
- Quantization applied in `PriceTracker.update()` before returning metrics dict.
- Quantization scales are constants in `synthdesk/listener/constants.py`.
- Unit tests MUST verify quantized values match expected integers (no float comparison tolerance).

### Sampling
- Window size `W` is a config parameter, emitted as metadata.
- `actual_window_size` computed as `min(W, len(history))` and emitted per tick.
- State persistence (`state_<PAIR>.json`) ensures windows survive restarts without interpolation.

---

## Non-Goals

- This policy does NOT require **timestamp string format determinism** (ISO8601 is acceptable with any UTC representation).
- This policy does NOT require **price input determinism** (upstream Binance API variance is expected; gaps and jitter are reality).
- This policy does NOT require **zero gaps** (gaps are observable, not failures).

---

## What IS Required (Summary)

- **Temporal**: Monotonicity violations and gaps MUST be logged deterministically.
- **Numeric**: Internal numerical transforms that influence emitted integers MUST be deterministic (integer-canonical windows per Pillar 2 §2.7.4).
- **Sampling**: Window rules MUST be explicit, and partial/gapped windows MUST emit correct metadata.
- **Third-party libraries**: If using NumPy/SciPy, pin versions and verify replay stability. Prefer stdlib `math` for core stats.
