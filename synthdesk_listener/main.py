from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .callbacks.on_regime_shift import handle_regime_shift
from .listeners.price_listener import PriceListener, fetch_prices
from .utils.atomic import atomic_write_json, safe_append_text, safe_append_csv
from .utils.logging_utils import configure_logging
from .version import VERSION

DEFAULT_CONFIG: Dict[str, Any] = {
    "poll_interval_seconds": 10,
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "vol_window": 60,
    "breakout_threshold": 0.015,
    "mr_band_width": 0.01,
    "log_level": "INFO",
    "log_file": None,
    "signals_dir": "signals",
}


def _get_run_day_dir() -> Path:
    """
    Return the runs/<VERSION>/<YYYY-MM-DD> directory, creating it if needed.
    """
    base = Path(__file__).resolve().parents[1] / "runs" / VERSION
    day_dir = base / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load configuration from JSON and apply defaults."""
    with config_path.open() as handle:
        loaded = json.load(handle)
    config = {**DEFAULT_CONFIG, **loaded}
    return config


def run(config_path: Optional[str] = None) -> None:
    resolved_path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
    config = load_config(resolved_path)

    logger = configure_logging(config.get("log_level", "INFO"), log_file=config.get("log_file"))

    run_meta = {
        "version": VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pairs": config.get("pairs"),
        "poll_interval": config.get("poll_interval_seconds"),
        "log_level": config.get("log_level"),
    }
    base = Path(__file__).resolve().parents[1] / "runs" / VERSION
    base.mkdir(parents=True, exist_ok=True)
    meta_path = base / "run_meta.json"
    atomic_write_json(meta_path, run_meta)

    day_dir = _get_run_day_dir()
    prices_path = day_dir / "prices.csv"
    heartbeat_path = day_dir / "heartbeat.log"

    base_dir = resolved_path.parent
    signals_dir = base_dir / config.get("signals_dir", "signals")
    signals_dir.mkdir(parents=True, exist_ok=True)

    listener = PriceListener(
        pairs=config["pairs"],
        vol_window=int(config["vol_window"]),
        breakout_threshold=float(config["breakout_threshold"]),
        band_width=float(config["mr_band_width"]),
        callback=lambda event: handle_regime_shift(event, signals_dir, logger=logger),
        logger=logger,
    )

    poll_interval = max(1, int(config.get("poll_interval_seconds", 10)))

    logger.info("Starting listener for pairs %s with poll interval %ss", config["pairs"], poll_interval)
    try:
        while True:
            hb_ts = datetime.now(timezone.utc).isoformat()
            safe_append_text(heartbeat_path, f"{hb_ts} alive")
            prices = fetch_prices(config["pairs"], logger=logger)
            now_ts = datetime.now(timezone.utc).isoformat()
            for pair, price in prices.items():
                if price is not None:
                    header = ["timestamp", "pair", "price"]
                    row = [now_ts, pair, price]
                    safe_append_csv(prices_path, row, header=header)
                listener.process_tick(pair, price, timestamp=now_ts)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Stopping listener (keyboard interrupt)")


def cli(argv: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="SynthDesk Listener v0.1")
    parser.add_argument("-c", "--config", dest="config", help="Path to config.json", required=False)
    args = parser.parse_args(list(argv) if argv is not None else None)
    run(args.config)


if __name__ == "__main__":
    cli()
