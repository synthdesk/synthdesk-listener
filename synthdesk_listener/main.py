from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import synthdesk_spine
from synthdesk_spine import EventEnvelope, EVENT_ENVELOPE_VERSION
from synthdesk.event_spine_writer import append_event_spine
from synthdesk.constants import REGIME_EPOCH_START_DT
from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.price_listener import PriceListener, fetch_prices
from synthdesk.listener.replay import classify_regime
from synthdesk.listener.version import VERSION
from synthdesk.utils.logging_utils import configure_logging

# Spine SDK version contract
REQUIRED_SPINE_MAJOR = 0
REQUIRED_SPINE_MINOR = 1

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


def _check_spine_version() -> tuple[str, bool]:
    """
    Check spine SDK version against contract.

    Returns (version_string, has_warning) where:
    - version_string: actual spine SDK version
    - has_warning: True if minor version mismatch (logged but not fatal)

    Raises RuntimeError if major version mismatch.
    """
    actual_version = synthdesk_spine.__version__
    try:
        parts = actual_version.split(".")
        actual_major = int(parts[0])
        actual_minor = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        raise RuntimeError(
            f"Invalid spine SDK version format: {actual_version} "
            f"(expected semver X.Y.Z)"
        )

    # Hard fail on major version mismatch
    if actual_major != REQUIRED_SPINE_MAJOR:
        raise RuntimeError(
            f"Spine SDK major version mismatch: found {actual_version}, "
            f"required {REQUIRED_SPINE_MAJOR}.x\n"
            f"This listener cannot run with incompatible spine SDK major version."
        )

    # Warn on minor version mismatch
    has_warning = actual_minor != REQUIRED_SPINE_MINOR
    return actual_version, has_warning


def _emit_listener_event(event_spine_path: Path, event_type: str, payload: Dict[str, Any]) -> None:
    event = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        source="synthdesk_listener",
        version=VERSION,
        schema_version=EVENT_ENVELOPE_VERSION,
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


def _normalize_for_hash(obj: Any) -> Any:
    if isinstance(obj, dict):
        normalized: Dict[Any, Any] = {}
        for key in sorted(obj.keys(), key=lambda item: str(item)):
            value = obj[key]
            normalized_key = key if _is_jsonable(key) else str(key)
            normalized[normalized_key] = _normalize_for_hash(value)
        return normalized
    if isinstance(obj, (list, tuple)):
        return [_normalize_for_hash(item) for item in obj]
    if isinstance(obj, float):
        return round(obj, 8)
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return obj if _is_jsonable(obj) else str(obj)


def _is_jsonable(obj: Any) -> bool:
    try:
        json.dumps(obj)
    except (TypeError, ValueError):
        return False
    return True


def _stable_event_id(event_type: str, tick_ts: str, payload: Dict[str, Any]) -> str:
    normalized_payload = _normalize_for_hash(payload)
    canonical = {"event_type": event_type, "tick_ts": tick_ts, "payload": normalized_payload}
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


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
        # Check spine SDK version before doing anything else
        spine_version, spine_version_warning = _check_spine_version()

        resolved_path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
        config = load_config(resolved_path)

        vol_window = config.get("vol_window")
        if not isinstance(vol_window, int) or isinstance(vol_window, bool) or vol_window <= 1:
            _emit_invariant_violation(
                event_spine_path,
                "listener.vol_window_invalid",
                "warning",
                vol_window,
                "vol_window must be int > 1",
                "degraded",
            )
            config["vol_window"] = 2

        logger = configure_logging(config.get("log_level", "INFO"), log_file=config.get("log_file"))

        # Log spine version warning if present
        if spine_version_warning:
            logger.warning(
                "Spine SDK minor version mismatch: found %s, expected %d.%d",
                spine_version,
                REQUIRED_SPINE_MAJOR,
                REQUIRED_SPINE_MINOR,
            )

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
        window_label = f"{int(config.get('vol_window', 0))}ticks"

        # Emit listener.start with full version metadata for auditability
        listener_start_payload = {
            "pairs": config.get("pairs"),
            "poll_interval_seconds": poll_interval,
            "spine_sdk_version": spine_version,
            "python_version": sys.version.split()[0],  # e.g., "3.12.3"
        }
        if spine_version_warning:
            listener_start_payload["spine_version_warning"] = (
                f"minor version mismatch: expected {REQUIRED_SPINE_MAJOR}.{REQUIRED_SPINE_MINOR}"
            )

        _emit_listener_event(
            event_spine_path,
            "listener.start",
            listener_start_payload,
        )

        listener = PriceListener(
            pairs=config["pairs"],
            vol_window=int(config["vol_window"]),
            logger=logger,
        )
        prev_regime_by_symbol: Dict[str, str] = {}

        logger.info("Starting listener for pairs %s with poll interval %ss", config["pairs"], poll_interval)
        while True:
            now_dt = datetime.now(timezone.utc)
            hb_ts = now_dt.isoformat()
            safe_append_text(heartbeat_path, f"{hb_ts} alive")
            prices = fetch_prices(config["pairs"], logger=logger)
            now_ts = now_dt.isoformat()
            tick_dt = _parse_iso8601(now_ts) or now_dt
            if tick_dt.tzinfo is None:
                tick_dt = tick_dt.replace(tzinfo=timezone.utc)
            else:
                tick_dt = tick_dt.astimezone(timezone.utc)
            is_post_epoch = tick_dt >= REGIME_EPOCH_START_DT
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
                metrics = listener.process_tick(pair, price, timestamp=now_ts)
                if isinstance(metrics, dict) and metrics:
                    invalid_metrics: Dict[str, Any] = {}
                    required_fields = (
                        "log_return",
                        "rolling_mean",
                        "rolling_std",
                        "zscore",
                        "slope",
                        "range",
                        "rolling_correlation",
                    )
                    for field in required_fields:
                        value = metrics.get(field)
                        if value is None:
                            invalid_metrics[field] = value
                        elif isinstance(value, (int, float)) and not isinstance(value, bool):
                            if not math.isfinite(value):
                                invalid_metrics[field] = value
                    if invalid_metrics:
                        _emit_invariant_violation(
                            event_spine_path,
                            "listener.metrics_invalid",
                            "warning",
                            invalid_metrics,
                            "all required metrics finite and non-null",
                            "ignored",
                        )
                if is_post_epoch:
                    regime_metrics: Dict[str, float] = {}
                    if isinstance(metrics, dict):
                        returns_mean = metrics.get("rolling_mean")
                        returns_std = metrics.get("rolling_std")
                        if (
                            isinstance(returns_mean, (int, float))
                            and not isinstance(returns_mean, bool)
                            and isinstance(returns_std, (int, float))
                            and not isinstance(returns_std, bool)
                        ):
                            regime_metrics = {
                                "returns_mean": float(returns_mean),
                                "returns_std": float(returns_std),
                            }
                            if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
                                range_value = metrics.get("range")
                                if isinstance(range_value, (int, float)) and not isinstance(range_value, bool):
                                    regime_metrics["range_pct"] = float(range_value) / float(price)
                    regime, confidence = classify_regime(pair, regime_metrics, tick_dt.timestamp())
                    tick_ts = tick_dt.astimezone(timezone.utc).isoformat()
                    regime_payload = {
                        "symbol": pair,
                        "regime": regime,
                        "confidence": confidence,
                        "window": window_label,
                        "tick_ts": tick_ts,
                    }
                    regime_event_id = (
                        _stable_event_id("market.regime", tick_ts, regime_payload)
                        if is_post_epoch
                        else str(uuid.uuid4())
                    )
                    try:
                        append_event_spine(
                            event_spine_path,
                            EventEnvelope(
                                event_id=regime_event_id,
                                event_type="market.regime",
                                timestamp=tick_dt.astimezone(timezone.utc),
                                source="synthdesk_listener",
                                version=VERSION,
                                schema_version=EVENT_ENVELOPE_VERSION,
                                host=socket.gethostname(),
                                payload=regime_payload,
                            ),
                        )
                    except OSError:
                        pass
                    prev_regime = prev_regime_by_symbol.get(pair)
                    if prev_regime is None:
                        prev_regime_by_symbol[pair] = regime
                    elif prev_regime != regime:
                        regime_change_payload = {
                            "symbol": pair,
                            "from": prev_regime,
                            "to": regime,
                            "confidence": confidence,
                            "window": window_label,
                        }
                        regime_change_event_id = (
                            _stable_event_id("market.regime_change", tick_ts, regime_change_payload)
                            if is_post_epoch
                            else str(uuid.uuid4())
                        )
                        try:
                            append_event_spine(
                                event_spine_path,
                                EventEnvelope(
                                    event_id=regime_change_event_id,
                                    event_type="market.regime_change",
                                    timestamp=tick_dt.astimezone(timezone.utc),
                                    source="synthdesk_listener",
                                    version=VERSION,
                                    schema_version=EVENT_ENVELOPE_VERSION,
                                    host=socket.gethostname(),
                                    payload=regime_change_payload,
                                ),
                            )
                        except OSError:
                            pass
                        prev_regime_by_symbol[pair] = regime
                if prev_ts is not None and now_ts <= prev_ts:
                    _emit_invariant_violation(
                        event_spine_path,
                        "listener.timestamp_non_monotonic",
                        "warning",
                        {"prev_ts": prev_ts, "now_ts": now_ts},
                        "timestamps strictly increasing",
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
