"""Price listener utilities for fetching data and emitting belief-free metrics."""

from __future__ import annotations

import json
import math
import random
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.transforms import log_return, log_returns, price_range, rolling_corr, rolling_mean, rolling_std, slope, zscore
from synthdesk.listener.version import VERSION


# =============================================================================
# Per-Symbol Normalization Constants (Frozen)
# =============================================================================
# These constants define the EWMA volatility estimator used to normalize
# returns into z-space before regime classification.
#
# DO NOT MODIFY without understanding the implications for regime thresholds.
# =============================================================================

# EWMA decay factor: λ = exp(ln(0.5) / H) where H = half-life in ticks
# For 30-minute half-life at 10s tick interval: H = 180 ticks
EWMA_LAMBDA = 0.9962  # exp(ln(0.5) / 180) ≈ 0.99615

# Minimum σ floor to prevent division by zero at startup or during stale periods
SIGMA_MIN = 1e-8

# Quantization factor for deterministic emission (6 decimal places)
Z_QUANTIZATION = 1_000_000

# =============================================================================
# Phase 1 Perception Expansion Constants (Frozen 2026-01-20)
# =============================================================================
# These constants define the second-order statistics for perception expansion.
# Changing these invalidates prior hypothesis evaluations.
# Court reference: FEATURESPEC_v1.0.0.json
# =============================================================================

# Vol-of-vol: rolling std of z_std over N windows (population variance)
VOL_OF_VOL_WINDOW = 10  # Number of z_std observations for std calculation

# Volume momentum: EWMA baseline with half-life L windows
VOLUME_EWMA_HALFLIFE = 20  # Half-life in windows for volume EWMA
VOLUME_EWMA_ALPHA = 2.0 / (VOLUME_EWMA_HALFLIFE + 1)  # α = 2/(L+1)


def _quantize_z(value: float) -> float:
    """
    Quantize z-space value to 6 decimal places for deterministic emission.
    This prevents floating-point drift across different platforms/runs.
    """
    return round(value * Z_QUANTIZATION) / Z_QUANTIZATION

API_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
KLINES_URL_TEMPLATE = (
    "https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}"
    "&startTime={start_ms}&endTime={end_ms}&limit=1"
)
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_S = 0.5
DEFAULT_RETRY_MAX_DELAY_S = 5.0
DEFAULT_RETRY_JITTER_RATIO = 0.2


def _compute_retry_delay(
    attempt: int,
    base_delay_s: float,
    max_delay_s: float,
    jitter_ratio: float,
) -> float:
    delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
    if jitter_ratio > 0:
        jitter = delay * jitter_ratio
        delay = max(0.0, delay + random.uniform(-jitter, jitter))
    return delay


def _binance_interval_from_seconds(interval_seconds: int) -> Optional[str]:
    interval_map = {
        60: "1m",
        180: "3m",
        300: "5m",
        900: "15m",
        3600: "1h",
    }
    return interval_map.get(interval_seconds)


def fetch_price(
    pair: str,
    logger=None,
    *,
    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_S,
    jitter_ratio: float = DEFAULT_RETRY_JITTER_RATIO,
) -> Optional[Tuple[float, datetime, datetime, str]]:
    """
    Fetch latest price and timestamps from Binance public API.

    Returns:
        (price, exchange_ts, receipt_ts, ts_authority) tuple or None on failure.

    Note: Binance /api/v3/ticker/price does NOT provide exchange timestamps,
    so exchange_ts == receipt_ts and ts_authority is always "receipt_fallback".
    """
    url = API_URL.format(symbol=pair)
    max_attempts = max(1, int(max_attempts))

    for attempt in range(1, max_attempts + 1):
        receipt_ts = datetime.now(timezone.utc)  # Capture immediately at ingestion boundary
        try:
            with urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                price_str = data.get("price") if isinstance(data, dict) else None
                if price_str is None:
                    if logger:
                        logger.warning("Unexpected response for %s: %s", pair, data)
                    return None

                price = float(price_str)

                # Binance /api/v3/ticker/price does NOT provide exchange timestamp
                # Use receipt_ts as fallback (explicit, not silent)
                exchange_ts = receipt_ts
                ts_authority = "receipt_fallback"

                return (price, exchange_ts, receipt_ts, ts_authority)
        except HTTPError as exc:
            status = exc.code
            retryable = status in RETRYABLE_HTTP_STATUSES
            if not retryable or attempt >= max_attempts:
                if logger:
                    logger.error("Failed to fetch price for %s (HTTP %s): %s", pair, status, exc)
                return None
            delay = _compute_retry_delay(attempt, base_delay_s, max_delay_s, jitter_ratio)
            if logger:
                logger.warning(
                    "Retrying price fetch for %s after HTTP %s in %.2fs (%s/%s)",
                    pair,
                    status,
                    delay,
                    attempt,
                    max_attempts,
                )
            time.sleep(delay)
        except (URLError, ValueError) as exc:
            if attempt >= max_attempts:
                if logger:
                    logger.error("Failed to fetch price for %s: %s", pair, exc)
                return None
            delay = _compute_retry_delay(attempt, base_delay_s, max_delay_s, jitter_ratio)
            if logger:
                logger.warning(
                    "Retrying price fetch for %s in %.2fs (%s/%s): %s",
                    pair,
                    delay,
                    attempt,
                    max_attempts,
                    exc,
                )
            time.sleep(delay)


def fetch_prices(
    pairs: Iterable[str],
    logger=None,
    *,
    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_S,
    jitter_ratio: float = DEFAULT_RETRY_JITTER_RATIO,
) -> Dict[str, Tuple[float, datetime, datetime, str]]:
    """
    Fetch prices and timestamps for multiple pairs, skipping failures.

    Returns:
        Dict mapping pair -> (price, exchange_ts, receipt_ts, ts_authority)
    """
    results: Dict[str, Tuple[float, datetime, datetime, str]] = {}
    for pair in pairs:
        result = fetch_price(
            pair,
            logger=logger,
            max_attempts=max_attempts,
            base_delay_s=base_delay_s,
            max_delay_s=max_delay_s,
            jitter_ratio=jitter_ratio,
        )
        if result is not None:
            results[pair] = result
    return results


def fetch_kline_volume(
    pair: str,
    *,
    interval_seconds: int,
    interval_start_ms: int,
    logger=None,
    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_RETRY_MAX_DELAY_S,
    jitter_ratio: float = DEFAULT_RETRY_JITTER_RATIO,
) -> Optional[Tuple[float, int]]:
    interval = _binance_interval_from_seconds(interval_seconds)
    if interval is None:
        if logger:
            logger.error("Unsupported kline interval seconds: %s", interval_seconds)
        return None
    start_ms = int(interval_start_ms)
    end_ms = start_ms + (interval_seconds * 1000) - 1
    url = KLINES_URL_TEMPLATE.format(
        symbol=pair,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    max_attempts = max(1, int(max_attempts))

    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, list) or not data:
                    if logger:
                        logger.warning("Unexpected kline response for %s: %s", pair, data)
                    return None
                kline = data[0]
                if not isinstance(kline, list) or len(kline) < 6:
                    if logger:
                        logger.warning("Invalid kline schema for %s: %s", pair, kline)
                    return None
                open_time_ms = int(kline[0])
                volume = float(kline[5])
                if open_time_ms != start_ms:
                    if logger:
                        logger.warning(
                            "Kline open_time mismatch for %s: expected=%s got=%s",
                            pair,
                            start_ms,
                            open_time_ms,
                        )
                    return None
                return volume, open_time_ms
        except HTTPError as exc:
            status = exc.code
            retryable = status in RETRYABLE_HTTP_STATUSES
            if not retryable or attempt >= max_attempts:
                if logger:
                    logger.error("Failed to fetch kline volume for %s (HTTP %s): %s", pair, status, exc)
                return None
            delay = _compute_retry_delay(attempt, base_delay_s, max_delay_s, jitter_ratio)
            if logger:
                logger.warning(
                    "Retrying kline fetch for %s after HTTP %s in %.2fs (%s/%s)",
                    pair,
                    status,
                    delay,
                    attempt,
                    max_attempts,
                )
            time.sleep(delay)
        except (URLError, ValueError) as exc:
            if attempt >= max_attempts:
                if logger:
                    logger.error("Failed to fetch kline volume for %s: %s", pair, exc)
                return None
            delay = _compute_retry_delay(attempt, base_delay_s, max_delay_s, jitter_ratio)
            if logger:
                logger.warning(
                    "Retrying kline fetch for %s in %.2fs (%s/%s): %s",
                    pair,
                    delay,
                    attempt,
                    max_attempts,
                    exc,
                )
            time.sleep(delay)
    return None


class PriceTracker:
    """Track rolling metrics for a single pair with per-symbol normalization."""

    def __init__(self, pair: str, window: int) -> None:
        self.pair = pair
        self.window = window
        self.long_window = window
        self.short_window = min(max(5, window // 3), window)
        self.prices: deque[float] = deque(maxlen=window)

        # Z-space: normalized returns buffer (same window as prices)
        self.z_returns: deque[float] = deque(maxlen=window)
        self.z_mean_history: deque[float] = deque(maxlen=window)

        # EWMA volatility state (per-symbol)
        self.ewma_var: float = 0.0
        self.ewma_sigma: float = 0.0
        self.ewma_initialized: bool = False

        # =================================================================
        # Phase 1 Perception Expansion State (2026-01-20)
        # =================================================================
        # z_std history for vol-of-vol calculation
        self.z_std_history: deque[float] = deque(maxlen=VOL_OF_VOL_WINDOW)

        # Volume EWMA baseline for volume momentum
        self.volume_history: deque[float] = deque(maxlen=window)
        self.ewma_volume: float = 0.0
        self.ewma_volume_initialized: bool = False

    def save_state(self, path: Path) -> None:
        data = {
            "pair": self.pair,
            "prices": list(self.prices),
            "z_returns": list(self.z_returns),
            "z_mean_history": list(self.z_mean_history),
            "short_window": self.short_window,
            "long_window": self.long_window,
            "ewma_var": self.ewma_var,
            "ewma_sigma": self.ewma_sigma,
            "ewma_initialized": self.ewma_initialized,
            # Phase 1 perception expansion state
            "z_std_history": list(self.z_std_history),
            "volume_history": list(self.volume_history),
            "ewma_volume": self.ewma_volume,
            "ewma_volume_initialized": self.ewma_volume_initialized,
        }
        atomic_write_json(path, data)

    def load_state(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # restore rolling window using long_window as maxlen
        self.prices = deque(data["prices"], maxlen=self.long_window)
        # restore z-space state (backwards compatible)
        self.z_returns = deque(data.get("z_returns", []), maxlen=self.long_window)
        self.z_mean_history = deque(data.get("z_mean_history", []), maxlen=self.long_window)
        self.ewma_var = data.get("ewma_var", 0.0)
        self.ewma_sigma = data.get("ewma_sigma", 0.0)
        self.ewma_initialized = data.get("ewma_initialized", False)
        # Phase 1 perception expansion state (backwards compatible)
        self.z_std_history = deque(data.get("z_std_history", []), maxlen=VOL_OF_VOL_WINDOW)
        self.volume_history = deque(data.get("volume_history", []), maxlen=self.long_window)
        self.ewma_volume = data.get("ewma_volume", 0.0)
        self.ewma_volume_initialized = data.get("ewma_volume_initialized", False)

    def update(self, price: float, volume: Optional[float] = None) -> Dict[str, Any]:
        """
        Update tracker with new price tick and optional volume.

        Args:
            price: Current price
            volume: Optional window volume (from OHLCV). If None, volume
                    momentum primitives will be None in output.

        Returns:
            Dict of computed metrics including phase-1 primitives.
        """
        self.prices.append(price)
        history: List[float] = list(self.prices)
        if not history:
            return {}

        if len(history) < 2:
            return {
                "log_return": 0.0,
                "z_return": 0.0,
                "z_mean": 0.0,
                "z_std": 0.0,
                "ewma_sigma": 0.0,
                "rolling_mean": 0.0,
                "rolling_std": 0.0,
                "zscore": 0.0,
                "slope": 0.0,
                "range": 0.0,
            }

        # Compute raw log return
        try:
            last_lr = log_return(history[-2], history[-1])
        except ValueError:
            last_lr = 0.0

        # =================================================================
        # EWMA Volatility Update (per-symbol normalization)
        # =================================================================
        # v_t = λ * v_{t-1} + (1-λ) * r_t²
        # σ_t = sqrt(v_t)
        # z_t = r_t / max(σ_t, σ_min)
        # =================================================================
        if not self.ewma_initialized:
            # Initialize with first return's squared value (avoid startup bias)
            self.ewma_var = last_lr * last_lr
            self.ewma_initialized = True
        else:
            self.ewma_var = EWMA_LAMBDA * self.ewma_var + (1 - EWMA_LAMBDA) * (last_lr * last_lr)

        self.ewma_sigma = math.sqrt(self.ewma_var)

        # Compute normalized z-return
        z_return = last_lr / max(self.ewma_sigma, SIGMA_MIN)

        # Append z-return to rolling buffer (this is what regime classification uses)
        self.z_returns.append(z_return)

        # =================================================================
        # Z-Space Rolling Features (for regime classification)
        # =================================================================
        z_list = list(self.z_returns)
        z_mean = rolling_mean(z_list, len(z_list)) if z_list else 0.0
        z_std = rolling_std(z_list, len(z_list)) if z_list else 0.0
        z_mean_q = _quantize_z(z_mean)
        z_std_q = _quantize_z(z_std)
        self.z_mean_history.append(z_mean_q)

        # =================================================================
        # Phase 1 Perception Expansion (2026-01-20)
        # =================================================================
        # 1. Drift acceleration: delta_z_mean = z_mean_t - z_mean_{t-1}
        #    Captures: "drift building vs drift fading"
        # 2. Vol-of-vol: std of z_std over last N windows (population variance)
        #    Captures: regime instability / transition noise
        # 3. Volume momentum: (volume - ewma_volume) / ewma_volume
        #    Captures: participation change vs baseline
        # =================================================================

        # 1. Drift acceleration
        delta_z_mean: Optional[float] = None
        if len(self.z_mean_history) >= 2:
            delta_z_mean = _quantize_z(z_mean_q - self.z_mean_history[-2])

        # 2. Vol-of-vol: append z_std to history, compute population std
        self.z_std_history.append(z_std_q)
        z_std_std: Optional[float] = None
        if len(self.z_std_history) >= VOL_OF_VOL_WINDOW:
            z_std_list = list(self.z_std_history)
            # Population variance (not sample) for consistency
            n = len(z_std_list)
            z_std_mean = sum(z_std_list) / n
            z_std_var = sum((x - z_std_mean) ** 2 for x in z_std_list) / n
            z_std_std = _quantize_z(math.sqrt(z_std_var))

        # 3. Volume momentum: (volume - ewma_volume) / ewma_volume
        #    Only computed if volume is provided (from OHLCV data)
        delta_vol_norm: Optional[float] = None
        if volume is not None and volume >= 0:
            self.volume_history.append(volume)
            if not self.ewma_volume_initialized:
                # Seed with first volume observation
                self.ewma_volume = volume
                self.ewma_volume_initialized = True
            else:
                self.ewma_volume = (
                    VOLUME_EWMA_ALPHA * volume
                    + (1 - VOLUME_EWMA_ALPHA) * self.ewma_volume
                )

            # Compute normalized volume deviation from baseline
            if self.ewma_volume > 0:
                delta_vol_norm = _quantize_z((volume - self.ewma_volume) / self.ewma_volume)

        # =================================================================
        # Legacy Raw Metrics (kept for backwards compatibility)
        # =================================================================
        returns_window = min(self.long_window - 1, len(history) - 1)
        returns = log_returns(history, returns_window)

        mean = rolling_mean(returns, len(returns)) if returns else 0.0
        std = rolling_std(returns, len(returns)) if returns else 0.0
        z = zscore(last_lr, mean, std)

        n_slope = min(self.long_window - 1, len(history) - 1)
        current_slope = slope(history, n_slope) if n_slope > 0 else 0.0
        current_range = price_range(history, min(self.long_window, len(history)))

        return {
            # Z-space metrics (PRIMARY for regime classification)
            # Quantized for deterministic emission
            "z_return": _quantize_z(z_return),
            "z_mean": z_mean_q,
            "z_std": z_std_q,
            "ewma_sigma": _quantize_z(self.ewma_sigma),
            "z_mean_history": list(self.z_mean_history),
            # Phase 1 perception expansion (2026-01-20)
            # These are second-order measurements, not claims
            "delta_z_mean": delta_z_mean,  # drift acceleration (may be None)
            "z_std_std": z_std_std,  # vol-of-vol (may be None if insufficient history)
            "delta_vol_norm": delta_vol_norm,  # volume momentum (None if no volume provided)
            # Legacy raw metrics (kept for backwards compatibility)
            "log_return": last_lr,
            "rolling_mean": mean,
            "rolling_std": std,
            "zscore": z,
            "slope": current_slope,
            "range": current_range,
        }


class PriceListener:
    """Ingest prices and emit belief-free scalar metrics (no detectors)."""

    def __init__(
        self,
        pairs: Iterable[str],
        vol_window: int,
        logger=None,
        *,
        stateless: bool = False,
    ) -> None:
        self.pairs = list(pairs)
        self.vol_window = vol_window
        self.logger = logger
        self.stateless = stateless

        base = Path(__file__).resolve().parents[2] / "runs" / VERSION
        base.mkdir(parents=True, exist_ok=True)
        self.runs_base_dir = base
        self.seq_meta_path = base / "sequence_meta.json"

        self.tick_seq = 0
        if not self.stateless and self.seq_meta_path.exists():
            try:
                with self.seq_meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.tick_seq = int(data.get("last_tick_id", 0))
            except Exception:
                self.tick_seq = 0

        self.last_ts_per_pair: Dict[str, str] = {}
        self.trackers = {}
        day_dir = self._current_day_dir() if not self.stateless else None
        for pair in self.pairs:
            tracker = PriceTracker(pair, vol_window)
            if not self.stateless and day_dir:
                state_path = day_dir / f"state_{pair}.json"
                if state_path.exists():
                    tracker.load_state(state_path)
            self.trackers[pair] = tracker

    def _current_day_dir(self) -> Path:
        day_dir = self.runs_base_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def process_tick(
        self,
        pair: str,
        price: Optional[float],
        timestamp: Optional[str] = None,
        *,
        volume: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Process a new price tick and emit belief-free scalar metrics.
        """
        if timestamp is None:
            # fall back to UTC "now" if main ever passes None
            timestamp = datetime.now(timezone.utc).isoformat()

        self.tick_seq += 1
        tick_id = self.tick_seq
        day_dir = self._current_day_dir()

        tick_record = {
            "ts_utc": timestamp,
            "asset": pair,
            "price": price,
            "source": "binance",
        }
        if volume is not None:
            tick_record["volume"] = volume

        tick_obs_path = day_dir / "tick_observation.jsonl"
        with open(tick_obs_path, "a") as f:
            f.write(json.dumps(tick_record) + "\n")

        meta = {
            "last_tick_id": self.tick_seq,
            "updated_at": timestamp,
        }

        try:
            atomic_write_json(self.seq_meta_path, meta)
        except Exception:
            if self.logger:
                self.logger.warning("Failed to write sequence_meta.json", exc_info=True)

        last_ts = self.last_ts_per_pair.get(pair)
        if last_ts is not None and timestamp <= last_ts:
            msg = f"{timestamp}, pair={pair}, tick_id={tick_id}, non_monotonic_ts, prev={last_ts}"
            seq_log_path = day_dir / "sequence_integrity.log"
            safe_append_text(seq_log_path, msg)
            if self.logger:
                self.logger.warning(msg)
            return {}
        self.last_ts_per_pair[pair] = timestamp

        tracker = self.trackers.get(pair)
        if tracker is None or price is None:
            return {}
        metrics = tracker.update(price, volume=volume)
        if not metrics:
            return {}

        if not self.stateless:
            state_path = day_dir / f"state_{pair}.json"
            tracker.save_state(state_path)

        anchor = self.pairs[0] if self.pairs else None
        if anchor and anchor in self.trackers:
            a_prices = list(self.trackers[anchor].prices)
            b_prices = list(tracker.prices)
            window_prices = min(self.vol_window, len(a_prices), len(b_prices))
            if window_prices >= 2:
                a_returns = log_returns(a_prices[-window_prices:], window_prices - 1)
                b_returns = log_returns(b_prices[-window_prices:], window_prices - 1)
                window_rets = min(len(a_returns), len(b_returns))
                metrics["rolling_correlation"] = (
                    rolling_corr(a_returns[-window_rets:], b_returns[-window_rets:], window_rets)
                    if window_rets >= 2
                    else 0.0
                )
            else:
                metrics["rolling_correlation"] = 0.0
        else:
            metrics["rolling_correlation"] = 0.0

        # write combined tick log row
        header = [
            "timestamp",
            "pair",
            "price",
            "log_return",
            "rolling_mean",
            "rolling_std",
            "zscore",
            "slope",
            "range",
            "rolling_correlation",
        ]
        row = [
            timestamp,
            pair,
            price,
            metrics.get("log_return"),
            metrics.get("rolling_mean"),
            metrics.get("rolling_std"),
            metrics.get("zscore"),
            metrics.get("slope"),
            metrics.get("range"),
            metrics.get("rolling_correlation"),
        ]
        tick_log_path = day_dir / "tick_log.csv"
        safe_append_csv(tick_log_path, row, header=header)
        return metrics


__all__ = ["PriceListener", "fetch_prices", "fetch_kline_volume"]
