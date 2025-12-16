"""Price listener utilities for fetching data and running detectors."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

from synthdesk.listener.detectors.breakout import detect_breakout
from synthdesk.listener.detectors.mr_touch import detect_mr_touch
from synthdesk.listener.detectors.vol_spike import detect_vol_spike
from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.transforms import rolling_mean, rolling_std, rolling_volatility
from synthdesk.listener.version import VERSION

API_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"

SignalCallback = Callable[[dict], None]


def _get_day_dir() -> Path:
    base = Path(__file__).resolve().parents[2] / "runs" / VERSION
    day_dir = base / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def fetch_price(pair: str, logger=None) -> Optional[float]:
    """Fetch latest price for a trading pair from Binance public API."""
    url = API_URL.format(symbol=pair)
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            price_str = data.get("price") if isinstance(data, dict) else None
            if price_str is None:
                if logger:
                    logger.warning("Unexpected response for %s: %s", pair, data)
                return None
            return float(price_str)
    except (URLError, ValueError) as exc:
        if logger:
            logger.error("Failed to fetch price for %s: %s", pair, exc)
        return None


def fetch_prices(pairs: Iterable[str], logger=None) -> Dict[str, float]:
    """Fetch prices for multiple pairs, skipping failures."""
    prices: Dict[str, float] = {}
    for pair in pairs:
        price = fetch_price(pair, logger=logger)
        if price is not None:
            prices[pair] = price
    return prices


class PriceTracker:
    """Track rolling metrics for a single pair."""

    def __init__(self, pair: str, window: int) -> None:
        self.pair = pair
        self.window = window
        self.long_window = window
        self.short_window = min(max(5, window // 3), window)
        self.prices: deque[float] = deque(maxlen=window)

    def save_state(self, path: Path) -> None:
        data = {
            "pair": self.pair,
            "prices": list(self.prices),
            "short_window": self.short_window,
            "long_window": self.long_window,
        }
        atomic_write_json(path, data)

    def load_state(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # restore rolling window using long_window as maxlen
        self.prices = deque(data["prices"], maxlen=self.long_window)

    def update(self, price: float) -> Dict[str, float]:
        self.prices.append(price)
        history: List[float] = list(self.prices)
        if not history:
            return {}

        eff_window = min(self.long_window, len(history))
        mean = rolling_mean(history, eff_window)
        std = rolling_std(history, eff_window)

        if len(history) < 2:
            return {
                "rolling_mean": mean,
                "rolling_std": std,
                "long_vol": 0.0,
                "short_vol": 0.0,
                "history_length": len(history),
            }

        short_vol = rolling_volatility(history, min(len(history), self.short_window))
        long_vol = rolling_volatility(history, min(len(history), self.long_window))

        return {
            "rolling_mean": mean,
            "rolling_std": std,
            "long_vol": long_vol,
            "short_vol": short_vol,
            "history_length": len(history),
        }


class PriceListener:
    """Feed live prices into detectors and trigger callbacks on events."""

    def __init__(
        self,
        pairs: Iterable[str],
        vol_window: int,
        breakout_threshold: float,
        band_width: float,
        callback: Optional[SignalCallback] = None,
        logger=None,
    ) -> None:
        self.pairs = list(pairs)
        self.vol_window = vol_window
        self.breakout_threshold = breakout_threshold
        self.band_width = band_width
        self.callback = callback
        self.logger = logger

        base = Path(__file__).resolve().parents[2] / "runs" / VERSION
        base.mkdir(parents=True, exist_ok=True)
        self.seq_meta_path = base / "sequence_meta.json"

        self.tick_seq = 0
        if self.seq_meta_path.exists():
            try:
                with self.seq_meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.tick_seq = int(data.get("last_tick_id", 0))
            except Exception:
                self.tick_seq = 0

        day_dir = base / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        self.day_dir = day_dir
        self.last_ts_per_pair: Dict[str, str] = {}
        self.seq_log_path = self.day_dir / "sequence_integrity.log"
        self.tick_log_path = self.day_dir / "tick_log.csv"
        self.detector_trace_path = self.day_dir / "detector_trace.csv"
        self.tick_obs_path = self.day_dir / "tick_observation.jsonl"
        self.trackers = {}
        for pair in self.pairs:
            tracker = PriceTracker(pair, vol_window)
            state_path = self.day_dir / f"state_{pair}.json"
            if state_path.exists():
                tracker.load_state(state_path)
            self.trackers[pair] = tracker

    def process_tick(
        self, pair: str, price: Optional[float], timestamp: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Process a new price tick for a given pair and emit any detected events.
        """
        if timestamp is None:
            # fall back to UTC "now" if main ever passes None
            timestamp = datetime.now(timezone.utc).isoformat()

        self.tick_seq += 1
        tick_id = self.tick_seq

        tick_record = {
            "ts_utc": timestamp,
            "asset": pair,
            "price": price,
            "source": "binance",
        }

        with open(self.tick_obs_path, "a") as f:
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
            safe_append_text(self.seq_log_path, msg)
            if self.logger:
                self.logger.warning(msg)
            return []
        self.last_ts_per_pair[pair] = timestamp

        tracker = self.trackers.get(pair)
        if tracker is None or price is None:
            return []
        metrics = tracker.update(price)
        if not metrics:
            return []

        state_path = self.day_dir / f"state_{pair}.json"
        tracker.save_state(state_path)

        events = [
            detect_breakout(pair, price, metrics["rolling_mean"], self.breakout_threshold, timestamp),
            detect_vol_spike(pair, metrics["short_vol"], metrics["long_vol"], timestamp),
            detect_mr_touch(pair, price, metrics["rolling_mean"], self.band_width, timestamp),
        ]
        for ev in events:
            if ev is not None:
                ev["tick_id"] = tick_id

        # write combined tick log row
        header = [
            "timestamp",
            "pair",
            "price",
            "rolling_mean",
            "rolling_std",
            "short_vol",
            "long_vol",
            "breakout_fired",
            "vol_spike_fired",
            "mr_touch_fired",
        ]
        row = [
            timestamp,
            pair,
            price,
            metrics.get("rolling_mean"),
            metrics.get("rolling_std"),
            metrics.get("short_vol"),
            metrics.get("long_vol"),
            1 if events[0] is not None else 0,
            1 if events[1] is not None else 0,
            1 if events[2] is not None else 0,
        ]
        safe_append_csv(self.tick_log_path, row, header=header)

        # write detector trace
        header = [
            "timestamp",
            "pair",
            "breakout_fired",
            "vol_spike_fired",
            "mr_touch_fired",
        ]
        row = [
            timestamp,
            pair,
            1 if events[0] is not None else 0,
            1 if events[1] is not None else 0,
            1 if events[2] is not None else 0,
        ]
        safe_append_csv(self.detector_trace_path, row, header=header)
        emitted: List[Dict[str, Any]] = []
        for event in events:
            if event is not None:
                # attach shared metrics
                event.setdefault("metrics", {}).update(metrics)
                emitted.append(event)
                if self.callback:
                    self.callback(event)
        return emitted


__all__ = ["PriceListener", "fetch_prices"]

