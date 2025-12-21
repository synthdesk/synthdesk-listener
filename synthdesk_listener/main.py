from __future__ import annotations

import argparse
import csv
import json
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from synthdesk.event_envelope import EventEnvelope
from synthdesk.event_spine_writer import append_event_spine
from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.price_listener import PriceListener, fetch_prices
from synthdesk.listener.version import VERSION
from synthdesk.utils.logging_utils import configure_logging

DEFAULT_CONFIG: Dict[str, Any] = {
    "poll_interval_seconds": 10,
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "vol_window": 60,
    "log_level": "INFO",
    "log_file": None,
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


def _emit_listener_event(event_spine_path: Path, event_type: str, payload: Dict[str, Any]) -> None:
    event = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source="synthdesk_listener",
        version=VERSION,
        host=socket.gethostname(),
        payload=payload,
    )
    try:
        event_spine_path.parent.mkdir(parents=True, exist_ok=True)
        append_event_spine(event_spine_path, event)
    except OSError:
        return


def _parse_iso8601(timestamp: str) -> Optional[datetime]:
    try:
        candidate = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _emit_invariant_violation_payload(
    event_spine_path: Path,
    invariant_id: str,
    severity: str,
    details: Dict[str, Any],
    timestamp: Optional[str] = None,
) -> None:
    _emit_listener_event(
        event_spine_path,
        "invariant.violation",
        {
            "event_type": "invariant.violation",
            "invariant_id": invariant_id,
            "severity": severity,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "details": details,
        },
    )


def _emit_invariant_violation(
    event_spine_path: Path,
    invariant: str,
    severity: str,
    observed: Any,
    expected: str,
    action: str,
) -> None:
    _emit_invariant_violation_payload(
        event_spine_path,
        invariant,
        severity,
        {
            "observed": observed,
            "expected": expected,
            "action": action,
        },
    )


def run(config_path: Optional[str] = None) -> None:
    logger = None
    event_spine_path = Path(__file__).resolve().parents[1] / "runs" / VERSION / "event_spine.jsonl"
    try:
        resolved_path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
        config = load_config(resolved_path)

        logger = configure_logging(config.get("log_level", "INFO"), log_file=config.get("log_file"))

        listener_started_at = datetime.now(timezone.utc)
        heartbeat_gap_violation_emitted = False

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

        poll_interval = max(1, int(config.get("poll_interval_seconds", 10)))

        _emit_listener_event(
            event_spine_path,
            "listener.start",
            {
                "pairs": config.get("pairs"),
                "poll_interval_seconds": poll_interval,
            },
        )

        listener = PriceListener(
            pairs=config["pairs"],
            vol_window=int(config["vol_window"]),
            logger=logger,
        )

        logger.info("Starting listener for pairs %s with poll interval %ss", config["pairs"], poll_interval)
        while True:
            now_dt = datetime.now(timezone.utc)
            hb_ts = now_dt.isoformat()
            safe_append_text(heartbeat_path, f"{hb_ts} alive")
            prices = fetch_prices(config["pairs"], logger=logger)
            now_ts = now_dt.isoformat()
            if len(prices) != len(config["pairs"]):
                missing_pairs = [pair for pair in config["pairs"] if pair not in prices]
                if missing_pairs:
                    _emit_invariant_violation(
                        event_spine_path,
                        "listener.missing_observation",
                        "warning",
                        {"timestamp": now_ts, "missing_pairs": missing_pairs},
                        "observation for each configured pair in poll cycle",
                        "degraded",
                    )
            for pair, price in prices.items():
                prev_ts = listener.last_ts_per_pair.get(pair)
                if price is not None:
                    header = ["timestamp", "pair", "price"]
                    row = [now_ts, pair, price]
                    safe_append_csv(prices_path, row, header=header)
                listener.process_tick(pair, price, timestamp=now_ts)
                if prev_ts is not None and now_ts <= prev_ts:
                    _emit_invariant_violation(
                        event_spine_path,
                        "listener.non_monotonic_timestamp",
                        "warning",
                        {"pair": pair, "timestamp": now_ts, "previous": prev_ts},
                        "timestamp must be greater than previous per-pair timestamp",
                        "ignored",
                    )
            if not heartbeat_gap_violation_emitted:
                for pair in config["pairs"]:
                    last_ts = listener.last_ts_per_pair.get(pair)
                    last_dt = _parse_iso8601(last_ts) if last_ts else None
                    if last_dt is None:
                        last_dt = listener_started_at
                    gap_seconds = (now_dt - last_dt).total_seconds()
                    if gap_seconds > 30:
                        _emit_invariant_violation_payload(
                            event_spine_path,
                            "inv-heartbeat-gap-30s",
                            "critical",
                            {"reason": "heartbeat gap exceeded 30s"},
                            timestamp=now_ts,
                        )
                        heartbeat_gap_violation_emitted = True
                        break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        _emit_listener_event(event_spine_path, "listener.stop", {"reason": "keyboard_interrupt"})
        if logger is not None:
            logger.info("Stopping listener (keyboard interrupt)")
    except Exception as e:
        _emit_listener_event(
            event_spine_path,
            "listener.crash",
            {"exception_type": type(e).__name__, "message": str(e)},
        )
        # Ensure every crash emits a post-mortem suggestion (non-destructive).
        try:
            from synthdesk.ops.repair import dump_repair_suggestion

            dump_repair_suggestion(e)
        except Exception:
            pass
        raise


def cli(argv: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="SynthDesk Listener v0.1")
    parser.add_argument("-c", "--config", dest="config", help="Path to config.json", required=False)
    args = parser.parse_args(list(argv) if argv is not None else None)
    run(args.config)


if __name__ == "__main__":
    cli()
