STATUS: LAW (normative, constraining)
VIOLATION CONSEQUENCE: Implementations that deviate from these formulas are non-compliant.

# Level 1: Univariate Descriptive Core Specification

## Objective

Define the complete set of belief-free univariate statistics that constitute "robust 'what happened' math" for regime justification. All metrics are descriptive scalars with no embedded decisions, recommendations, or forecasts.

## Scope

Level 1 delivers sufficient statistics for univariate regime classification:
- Returns and volatility (already partially implemented)
- Volatility bucketing via quantiles (new)
- Heavy-tail diagnostics (new)

All emitted metrics are quantized integers per `level_0_determinism_policy.md`.

## Canonicalization Rule (Required for Determinism)

Per-tick log returns are quantized **immediately** to `log_return_int`. All rolling statistics MUST be computed from the integer series (or from floats derived solely from that integer series), not from raw float returns.

This ensures that float drift in internal computations does not leak into emitted integers via rounding-threshold wobble.

---

## 1. Log Returns

### Definition
Log return between consecutive prices `p_{t-1}` and `p_t`:

```
log_return_t = ln(p_t / p_{t-1})
```

### Edge Cases
- If `p_{t-1} <= 0` or `p_t <= 0`: emit `null` (or skip tick).
- First tick in a sequence: `log_return = null`.

### Window
- Per-tick: single return (t-1 to t).
- Rolling returns: last `W` returns for rolling statistics.

### Emission
- Quantized as integer using the deterministic quantization rule from `level_0_determinism_policy.md`:
  ```python
  log_return_int = quantize(log_return, scale=100000)  # 1e5
  ```

---

## 2. Realized Volatility

### Definition
Sample standard deviation of log returns over window `W`, computed from **integer-canonical series**:

```
# Step 1: Collect integer log returns
lr_ints = [log_return_int_1, log_return_int_2, ..., log_return_int_W]

# Step 2: Convert to floats (scaled)
lr_floats = [lr_int / 100000.0 for lr_int in lr_ints]

# Step 3: Compute sample std dev
μ_r = sum(lr_floats) / W
variance = sum((r - μ_r)**2 for r in lr_floats) / (W - 1)
realized_vol_W = sqrt(variance)
```

where:
- `lr_ints` = quantized integer log returns (from canonicalization)
- `W >= 2` (otherwise emit `null`)

**Key**: Volatility is computed from the integer series, not from raw float returns, to avoid float drift leaking into the quantized output.

### Window W
- **Tick-count based**: last `W` ticks (not wall-clock time).
- Suggested default: `W = 60` (e.g., 60 ticks ≈ 1 minute at 1-second polling).
- Window size MUST be emitted as metadata: `"vol_window": W`.

### Emission
- Quantized as integer using the deterministic quantization rule:
  ```python
  realized_vol_int = quantize(realized_vol, scale=100000)  # 1e5
  ```

---

## 3. Volatility Buckets (Quantile-Based)

### Purpose
Classify current realized volatility as `low`, `mid`, or `high` relative to recent historical distribution.

### Reference Window R
- **R = 360 W-windows** (tick-count based).
- Example: If `W = 60 ticks`, then `R` spans the last `360 * 60 = 21,600 ticks` (≈ 6 hours at 1-second polling).
- During startup (if fewer than `R` samples exist), use all available history (minimum 10 samples required).

### Quantile Computation (Deterministic Method)
Use **nearest-rank quantiles** on **integer samples** (no interpolation):

```python
import math

def quantile_nearest_rank(data_ints: list[int], q: float) -> int:
    """
    Nearest-rank quantile on integer samples.
    q ∈ [0, 1].
    Returns an integer (no float interpolation).
    """
    data_sorted = sorted(data_ints)
    n = len(data_sorted)
    if n == 0:
        return None
    k = max(1, min(n, int(math.ceil(q * n))))  # 1-indexed rank
    return data_sorted[k - 1]
```

**Rationale**: Nearest-rank is simpler, avoids float interpolation (which can drift), and is sufficient for bucketing at level 1. Type 7 quantiles (with interpolation) can be considered for level 2 estimation refinements if needed.

### Cutpoints
Computed on **integer realized volatilities** (quantized `realized_vol_int` from last R windows):

- `vol_q33_int` = nearest-rank quantile at q=0.33 of last R `realized_vol_int` samples
- `vol_q66_int` = nearest-rank quantile at q=0.66 of last R `realized_vol_int` samples

### Bucket Assignment
```
# Compare integer values directly (no float comparison)
if realized_vol_int < vol_q33_int:
    vol_bucket = "low"
elif realized_vol_int < vol_q66_int:
    vol_bucket = "mid"
else:
    vol_bucket = "high"
```

### Emission
Emit as a tuple in metrics dict:
```json
{
  "realized_vol": 12300,         // quantized (1e5)
  "vol_bucket": "mid",           // string literal
  "vol_q33": 8500,               // quantized (1e5)
  "vol_q66": 15000,              // quantized (1e5)
  "vol_window_W": 60,            // int (tick count)
  "vol_reference_R": 360,        // int (window count)
  "vol_sample_count": 21600      // int (actual tick count in R)
}
```

### Edge Cases
- If fewer than 10 realized vol samples exist: emit `vol_bucket = null`, `vol_q33_int = null`, `vol_q66_int = null`.

---

## 4. Kurtosis (Excess Kurtosis)

### Definition
Fourth standardized moment of log returns over window W, computed from **integer-canonical series**:

```
# Step 1: Collect integer log returns
lr_ints = [log_return_int_1, log_return_int_2, ..., log_return_int_W]

# Step 2: Convert to floats (scaled)
lr_floats = [lr_int / 100000.0 for lr_int in lr_ints]

# Step 3: Compute kurtosis
μ_r = sum(lr_floats) / W
σ_r = sqrt(sum((r - μ_r)**2 for r in lr_floats) / (W - 1))

if σ_r == 0:
    kurtosis_excess = null
else:
    fourth_moment = (1/W) * sum(((r - μ_r) / σ_r)**4 for r in lr_floats)
    kurtosis_excess = fourth_moment - 3
```

where:
- `lr_ints` = quantized integer log returns (from canonicalization)
- `-3` adjustment gives "excess kurtosis" (normal distribution → 0)

**Normalization note**: Kurtosis uses population normalization (`1/W`) for the fourth moment and sample normalization (`1/(W-1)`) for variance. This choice is fixed and normative.

### Interpretation (Descriptive Only)
- `kurtosis > 0`: heavier tails than normal distribution (more extreme moves).
- `kurtosis ≈ 0`: tails similar to normal distribution.
- `kurtosis < 0`: lighter tails than normal distribution.

**No action or decision is implied.** This is purely a tail-shape descriptor.

### Window W
- Same as realized volatility window (typically 60 ticks).

### Edge Cases
- If `σ_r = 0` (constant prices): emit `null`.
- If `W < 4`: emit `null` (insufficient data for 4th moment).

### Emission
- Quantized as integer using the deterministic quantization rule:
  ```python
  kurtosis_excess_int = quantize(kurtosis_excess, scale=10000)  # 1e4
  ```
- Typical range: `-2.0` to `+10.0` → `-20000` to `+100000` (at scale 1e4).

---

## 5. Tail Quantile Ratio

### Definition
Ratio of upper tail to lower tail quantiles, computed from **integer-canonical series**:

```
# Step 1: Collect integer log returns
lr_ints = [log_return_int_1, log_return_int_2, ..., log_return_int_W]

# Step 2: Compute quantiles on integer samples
q_95_int = quantile_nearest_rank(lr_ints, 0.95)
q_05_int = quantile_nearest_rank(lr_ints, 0.05)

# Step 3: Convert to floats and compute ratio
q_95_float = q_95_int / 100000.0
q_05_float = q_05_int / 100000.0

if abs(q_05_float) < 1e-8:
    tail_ratio = undefined (emit -1)
else:
    tail_ratio = q_95_float / abs(q_05_float)
```

where:
- `q_95_int`, `q_05_int` = nearest-rank quantiles on integer log returns
- `|q_05|` = absolute value (lower tail is typically negative)

### Alternative Specification (Symmetric Tail Ratio)
If you want to capture tail asymmetry separately:

```
tail_ratio_symmetric = (q_95 - q_50) / (q_50 - q_05)
```

**Default for level 1: use `q_95 / |q_05|`** (simpler, captures tail heaviness).

### Interpretation (Descriptive Only)
- `tail_ratio > 1`: upper tail extends further than lower tail (positive skew in extremes).
- `tail_ratio ≈ 1`: symmetric tails.
- `tail_ratio < 1`: lower tail extends further (negative skew in extremes).

**No action or decision is implied.**

### Edge Cases (Guard Against Division by Zero)
- If `q_05_int == 0`: emit `tail_ratio_int = -1` (sentinel value).
  - Alternative formulation: If `|q_05_float| < 1e-8` (after converting from int).
  - Both are equivalent given integer-canonical inputs; the integer check is cleaner.
- Rationale: denominator near zero makes ratio unstable/meaningless.
- Sentinel semantics: `-1` (integer) means "undefined tail ratio."
- **No `null` values**: Always emit an integer (`-1` for undefined), so schema type remains `int`.

### Window W
- Same as realized volatility window (typically 60 ticks).

### Emission
- Quantized as integer using the deterministic quantization rule:
  ```python
  if |q_05_float| < 1e-8:
      tail_ratio_int = -1  # sentinel
  else:
      tail_ratio_float = q_95_float / abs(q_05_float)
      tail_ratio_int = quantize(tail_ratio_float, scale=10000)  # 1e4
  ```
- Sentinel: `-1` (integer) for undefined ratio.
- Example: `tail_ratio = 1.456` → `14560` (at scale 1e4).

---

## 6. Sufficient Statistics Mapping (Regime Justification)

### Purpose
These univariate stats collectively provide the observational basis for regime classification. Regimes are **descriptive labels**, not predictive signals.

### Mapping (Belief-Free, Descriptive Only)

| Regime Label | Example Sufficient Stats |
|--------------|--------------------------|
| `calm`       | `vol_bucket = "low"`, `kurtosis_excess < 1.0`, `tail_ratio ≈ 1.0` |
| `choppy`     | `vol_bucket = "mid"`, `kurtosis_excess > 2.0` |
| `volatile`   | `vol_bucket = "high"`, `kurtosis_excess > 3.0` |
| `tail_event` | `kurtosis_excess > 5.0`, `tail_ratio > 2.0` or `< 0.5` |

**Important**:
- These criteria are **descriptive annotations**, not triggers or signals.
- Downstream systems (e.g., `synthdesk_agency/`) may use these labels for context, but the listener itself does not decide, recommend, or act.
- Regimes are not yet formal hypothesis tests (that's level 2+).

### Emission
Regime labels (if computed) are emitted as:
```json
{
  "regime": "volatile",  // string literal
  "regime_confidence": 8500  // quantized (1e4), optional
}
```

But for level 1, **regime emission is optional**. The primary deliverable is the univariate stats themselves.

---

## Level 1 Completion Criteria

Level 1 is **done** when all of the following are true:

1. ✅ Listener emits (as deterministic quantized integers):
   - `log_return`
   - `realized_vol`
   - `vol_bucket` (+ `vol_q33`, `vol_q66`, window metadata)
   - `kurtosis_excess`
   - `tail_ratio` (with guard for undefined ratios)

2. ✅ Each emitted metric includes:
   - Window `W` (tick count)
   - Reference window `R` (for quantiles, if applicable)
   - Sample count (actual observations used)

3. ✅ Replay determinism passes:
   - Two runs with identical input ticks produce byte-identical `tick_log.csv` and event spine.

4. ✅ All formulas match this spec exactly (no implementation variants).

5. ✅ Edge cases (null guards, sentinel values) are documented and tested.

---

## Non-Goals for Level 1

- **Not included**: multivariate stats (correlation, cointegration) → that's level 2.
- **Not included**: regime hypothesis testing (Bayesian updates, confidence intervals) → that's level 2.
- **Not included**: strategy, alpha, edge, or execution logic → never in listener.

Level 1 is purely univariate, purely descriptive, purely observational.
