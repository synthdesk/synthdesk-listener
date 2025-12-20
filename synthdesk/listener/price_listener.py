"""Price listener utilities for fetching data and emitting belief-free metrics."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.transforms import log_return, log_returns, price_range, rolling_corr, rolling_mean, rolling_std, slope, zscore
from synthdesk.listener.version import VERSION

API_URL = "https://api.binance.com/api/v3/ticker/price?symbol={symbol}"


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

        if len(history) < 2:
            return {
                "log_return": 0.0,
                "rolling_mean": 0.0,
                "rolling_std": 0.0,
                "zscore": 0.0,
                "slope": 0.0,
                "range": 0.0,
            }

        try:
            last_lr = log_return(history[-2], history[-1])
        except ValueError:
            last_lr = 0.0

        returns_window = min(self.long_window - 1, len(history) - 1)
        returns = log_returns(history, returns_window)

        mean = rolling_mean(returns, len(returns)) if returns else 0.0
        std = rolling_std(returns, len(returns)) if returns else 0.0
        z = zscore(last_lr, mean, std)

        n_slope = min(self.long_window - 1, len(history) - 1)
        current_slope = slope(history, n_slope) if n_slope > 0 else 0.0
        current_range = price_range(history, min(self.long_window, len(history)))

        return {
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
    ) -> None:
        self.pairs = list(pairs)
        self.vol_window = vol_window
        self.logger = logger

        base = Path(__file__).resolve().parents[2] / "runs" / VERSION
        base.mkdir(parents=True, exist_ok=True)
        self.runs_base_dir = base
        self.seq_meta_path = base / "sequence_meta.json"

        self.tick_seq = 0
        if self.seq_meta_path.exists():
            try:
                with self.seq_meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.tick_seq = int(data.get("last_tick_id", 0))
            except Exception:
                self.tick_seq = 0

        self.last_ts_per_pair: Dict[str, str] = {}
        self.trackers = {}
        day_dir = self._current_day_dir()
        for pair in self.pairs:
            tracker = PriceTracker(pair, vol_window)
            state_path = day_dir / f"state_{pair}.json"
            if state_path.exists():
                tracker.load_state(state_path)
            self.trackers[pair] = tracker

    def _current_day_dir(self) -> Path:
        day_dir = self.runs_base_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def process_tick(
        self, pair: str, price: Optional[float], timestamp: Optional[str] = None
    ) -> Dict[str, float]:
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
        metrics = tracker.update(price)
        if not metrics:
            return {}

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


__all__ = ["PriceListener", "fetch_prices"]
