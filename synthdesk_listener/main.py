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
from synthdesk_spine.event_types import INVARIANT_VIOLATION
from synthdesk.event_spine_writer import append_event_spine
from synthdesk.constants import REGIME_EPOCH_START_DT
from synthdesk.listener.io.atomic import atomic_write_json, safe_append_csv, safe_append_text
from synthdesk.listener.price_listener import PriceListener, fetch_prices
from synthdesk.listener.regime_classifier import (
    classify_regime_full,
    REGIME_THRESHOLDS_V1,
    validate_window_config,
)
from synthdesk.listener.version import VERSION
from synthdesk.ops.startup_class import classify_startup
from synthdesk.utils.logging_utils import configure_logging

# Spine SDK version contract
# Soak obedience adapter version (for lifecycle events)
SOAK_ADAPTER_VERSION = "0.1.0"
REQUIRED_SPINE_MAJOR = 0
REQUIRED_SPINE_MINOR = 1

DEFAULT_CONFIG: Dict[str, Any] = {
    "poll_interval_seconds": 10,
    "pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "vol_window": 60,
    "log_level": "INFO",
    "log_file": None,
    "regime_debug": False,  # Emit market.regime_debug events with full decision audit
    "emit_phase1": False,
    "binance_retry_max_attempts": 3,
    "binance_retry_base_delay_seconds": 0.5,
    "binance_retry_max_delay_seconds": 5.0,
    "binance_retry_jitter_ratio": 0.2,
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
            "event_type": INVARIANT_VIOLATION,
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


# =============================================================================
# Soak Obedience Adapter
# =============================================================================
# These functions enable the listener to run under soak control plane governance.
# When mode="IGNORE" (default), none of this code executes — canonical behavior
# is mechanically preserved.


def _check_signal(signals_dir: Path, signal_name: str) -> bool:
    """Check if a signal file exists."""
    return (signals_dir / f"{signal_name}.json").exists()


def _consume_signal(signals_dir: Path, signal_name: str) -> Optional[Dict[str, Any]]:
    """
    Read and delete a signal file (atomic consumption).

    Returns signal data if successful, None otherwise.
    Always deletes file on read attempt to prevent infinite retry on malformed signals.
    """
    signal_path = signals_dir / f"{signal_name}.json"
    if not signal_path.exists():
        return None
    data = None
    try:
        with signal_path.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass  # Malformed or unreadable — still delete to prevent livelock
    # Always try to delete (prevents signal accumulation)
    try:
        signal_path.unlink()
    except OSError:
        pass  # Race: already consumed by another process
    return data


def _emit_lifecycle(
    lifecycle_log: Path,
    event: str,
    soak_id: str,
    run_id: str,
    **extra: Any,
) -> None:
    """Emit a lifecycle event to soak lifecycle log (best effort)."""
    if str(lifecycle_log) == "/dev/null":
        return
    record = {
        "event": event,
        "schema_version": SOAK_ADAPTER_VERSION,
        "soak_id": soak_id,
        "run_id": run_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "runner_type": "listener",
        **extra,
    }
    try:
        lifecycle_log.parent.mkdir(parents=True, exist_ok=True)
        with lifecycle_log.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # Best effort — don't crash listener for lifecycle IO


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

        # Validate window matches threshold calibration
        config_vol_window = int(config.get("vol_window", 60))
        if config_vol_window != REGIME_THRESHOLDS_V1.window_ticks:
            _emit_invariant_violation(
                event_spine_path,
                "listener.window_threshold_mismatch",
                "error",
                {
                    "config_window": config_vol_window,
                    "threshold_window": REGIME_THRESHOLDS_V1.window_ticks,
                    "thresholds_id": REGIME_THRESHOLDS_V1.thresholds_id,
                },
                f"vol_window must match threshold calibration ({REGIME_THRESHOLDS_V1.window_ticks})",
                "regime_classification_invalid",
            )

        logger = configure_logging(config.get("log_level", "INFO"), log_file=config.get("log_file"))

        # Soak control configuration (defaults to standalone/IGNORE mode)
        # When mode="IGNORE", no signal checking occurs — canonical behavior preserved.
        soak_config = config.get("soak", {})
        soak_mode = soak_config.get("mode", "IGNORE")
        soak_id = soak_config.get("soak_id", "standalone")
        signals_dir = Path(soak_config.get("signals_dir", "/dev/null"))
        lifecycle_log = Path(soak_config.get("lifecycle_log", "/dev/null"))
        soak_run_id = str(uuid.uuid4())

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

        base = Path(__file__).resolve().parents[1] / "runs" / VERSION
        base.mkdir(parents=True, exist_ok=True)
        meta_path = base / "run_meta.json"

        # Classify startup semantics BEFORE writing run_meta (so cold is detectable)
        startup_type, startup_meta = classify_startup(
            state_path=str(meta_path),
            lifecycle_path=str(lifecycle_log) if str(lifecycle_log) != "/dev/null" else None,
            ledger_path=None,  # listener does not own a ledger
        )

        run_meta = {
            "version": VERSION,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pairs": config.get("pairs"),
            "poll_interval": config.get("poll_interval_seconds"),
            "log_level": config.get("log_level"),
        }
        atomic_write_json(meta_path, run_meta)

        day_dir = _get_run_day_dir()
        prices_path = day_dir / "prices.csv"
        heartbeat_path = day_dir / "heartbeat.log"

        poll_interval = max(1, int(config.get("poll_interval_seconds", 10)))
        window_label = f"{int(config.get('vol_window', 0))}ticks"
        emit_phase1 = bool(config.get("emit_phase1", False))

        # Emit listener.start with full version metadata for auditability
        listener_start_payload = {
            "pairs": config.get("pairs"),
            "poll_interval_seconds": poll_interval,
            "spine_sdk_version": spine_version,
            "python_version": sys.version.split()[0],  # e.g., "3.12.3"
            "startup": {
                "startup_type": startup_type,
                "rule": startup_meta.get("rule"),
                "evidence": startup_meta.get("evidence"),
            },
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

        # Emit RUNNER_START if in OBEY mode (soak control plane integration)
        if soak_mode == "OBEY":
            _emit_lifecycle(
                lifecycle_log, "RUNNER_START", soak_id, soak_run_id,
                runner_mode=soak_mode,
                startup_type=startup_type,
                startup_rule=startup_meta.get("rule"),
                source_event_ts=datetime.now(timezone.utc).isoformat(),
            )

        listener = PriceListener(
            pairs=config["pairs"],
            vol_window=int(config["vol_window"]),
            logger=logger,
        )
        prev_regime_by_symbol: Dict[str, str] = {}

        logger.info("Starting listener for pairs %s with poll interval %ss", config["pairs"], poll_interval)

        # Soak obedience state (only meaningful when mode="OBEY")
        paused = False
        work_count = 0

        while True:
            # === Signal handling (only in OBEY mode) ===
            if soak_mode == "OBEY":
                # TERMINATE takes precedence — check first
                if _check_signal(signals_dir, "TERMINATE"):
                    signal_data = _consume_signal(signals_dir, "TERMINATE")
                    _emit_lifecycle(
                        lifecycle_log, "RUNNER_SIGNAL_SEEN", soak_id, soak_run_id,
                        signal="TERMINATE",
                        source_event_ts=signal_data.get("ts_utc") if signal_data else None,
                    )
                    _emit_lifecycle(lifecycle_log, "RUNNER_TERMINATED", soak_id, soak_run_id)
                    logger.info("Received TERMINATE signal, shutting down")
                    break

                # PAUSE — always consume to prevent accumulation
                if _check_signal(signals_dir, "PAUSE"):
                    signal_data = _consume_signal(signals_dir, "PAUSE")
                    _emit_lifecycle(
                        lifecycle_log, "RUNNER_SIGNAL_SEEN", soak_id, soak_run_id,
                        signal="PAUSE",
                        source_event_ts=signal_data.get("ts_utc") if signal_data else None,
                    )
                    if not paused:
                        paused = True
                        _emit_lifecycle(lifecycle_log, "RUNNER_PAUSED", soak_id, soak_run_id)
                        logger.info("Received PAUSE signal, pausing work")

                # RESUME — always consume to prevent accumulation
                if _check_signal(signals_dir, "RESUME"):
                    signal_data = _consume_signal(signals_dir, "RESUME")
                    _emit_lifecycle(
                        lifecycle_log, "RUNNER_SIGNAL_SEEN", soak_id, soak_run_id,
                        signal="RESUME",
                        source_event_ts=signal_data.get("ts_utc") if signal_data else None,
                    )
                    if paused:
                        paused = False
                        _emit_lifecycle(lifecycle_log, "RUNNER_RESUMED", soak_id, soak_run_id)
                        logger.info("Received RESUME signal, resuming work")

            # Skip work if paused (reuse poll_interval to preserve timing semantics)
            if paused:
                time.sleep(poll_interval)
                continue

            # === Emit work tick for soak observability ===
            work_count += 1
            if soak_mode == "OBEY":
                _emit_lifecycle(
                    lifecycle_log, "RUNNER_WORK_TICK", soak_id, soak_run_id,
                    work_count=work_count,
                    source_event_ts=datetime.now(timezone.utc).isoformat(),
                )

            # Capture observer receipt time at loop entry (used for lifecycle events)
            receipt_dt = datetime.now(timezone.utc)
            receipt_ts = receipt_dt.isoformat()

            safe_append_text(heartbeat_path, f"{receipt_ts} alive")

            # Fetch prices with timestamps (timestamp authority v0.1)
            price_results = fetch_prices(
                config["pairs"],
                logger=logger,
                max_attempts=config["binance_retry_max_attempts"],
                base_delay_s=config["binance_retry_base_delay_seconds"],
                max_delay_s=config["binance_retry_max_delay_seconds"],
                jitter_ratio=config["binance_retry_jitter_ratio"],
            )

            if len(price_results) != len(config["pairs"]):
                missing_pairs = [pair for pair in config["pairs"] if pair not in price_results]
                if missing_pairs:
                    _emit_invariant_violation(
                        event_spine_path,
                        "listener.missing_observation",
                        "warning",
                        {"timestamp": receipt_ts, "missing_pairs": missing_pairs},
                        "observation for each configured pair in poll cycle",
                        "degraded",
                    )

            for pair, (price, exchange_ts, tick_receipt_ts, ts_authority) in price_results.items():
                # Use exchange_ts as authoritative tick time
                tick_dt = exchange_ts
                tick_ts = tick_dt.isoformat()
                is_post_epoch = tick_dt >= REGIME_EPOCH_START_DT
                prev_ts = listener.last_ts_per_pair.get(pair)
                if price is not None:
                    header = ["timestamp", "pair", "price"]
                    row = [tick_ts, pair, price]
                    safe_append_csv(prices_path, row, header=header)
                metrics = listener.process_tick(pair, price, timestamp=tick_ts)
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
                    regime_metrics: Dict[str, Any] = {}
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
                        # Pass z_mean_history to enable drift_persist classification
                        z_mean_history = metrics.get("z_mean_history")
                        if isinstance(z_mean_history, list):
                            regime_metrics["z_mean_history"] = z_mean_history
                    # Use full classification for audit trail
                    classification = classify_regime_full(
                        pair, regime_metrics, tick_dt.timestamp(), REGIME_THRESHOLDS_V1
                    )
                    regime = classification.regime
                    confidence = classification.confidence
                    # Timestamp authority fields (v0.1)
                    latency_ms = int((tick_receipt_ts - exchange_ts).total_seconds() * 1000)
                    phase1_primitives = None
                    if emit_phase1 and isinstance(metrics, dict):
                        # Phase 1 perception expansion (2026-01-20)
                        # Extract second-order primitives from metrics
                        phase1_values: Dict[str, Any] = {}
                        delta_z_mean = metrics.get("delta_z_mean")
                        if delta_z_mean is not None:
                            phase1_values["delta_z_mean"] = delta_z_mean
                        z_std_std = metrics.get("z_std_std")
                        if z_std_std is not None:
                            phase1_values["z_std_std"] = z_std_std
                        delta_vol_norm = metrics.get("delta_vol_norm")
                        if delta_vol_norm is not None:
                            phase1_values["delta_vol_norm"] = delta_vol_norm
                        range_norm = metrics.get("range_norm")
                        if range_norm is not None:
                            phase1_values["range_norm"] = range_norm
                        if phase1_values:
                            phase1_primitives = phase1_values

                    regime_payload = {
                        "symbol": pair,
                        "regime": regime,
                        "confidence": confidence,
                        "window": window_label,
                        "thresholds_id": classification.thresholds_id,
                        "regime_model_id": classification.regime_model_id,
                        "window_ticks": REGIME_THRESHOLDS_V1.window_ticks,
                        "metrics": classification.to_payload_metrics(),
                        "tick_ts": tick_ts,
                        "exchange_ts": exchange_ts.isoformat(),
                        "receipt_ts": tick_receipt_ts.isoformat(),
                        "ts_authority": ts_authority,
                        "ts_source": "binance.rest.ticker_price",
                        "latency_ms": latency_ms,
                    }
                    if emit_phase1:
                        # Phase 1 perception expansion (may be empty if insufficient history)
                        regime_payload["phase1"] = phase1_primitives
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
                    # Emit debug event with full decision audit if enabled
                    if config.get("regime_debug", False):
                        debug_payload = classification.to_debug_payload()
                        debug_payload["tick_ts"] = tick_ts
                        debug_payload["symbol"] = pair
                        debug_event_id = _stable_event_id("market.regime_debug", tick_ts, debug_payload)
                        try:
                            append_event_spine(
                                event_spine_path,
                                EventEnvelope(
                                    event_id=debug_event_id,
                                    event_type="market.regime_debug",
                                    timestamp=tick_dt.astimezone(timezone.utc),
                                    source="synthdesk_listener",
                                    version=VERSION,
                                    schema_version=EVENT_ENVELOPE_VERSION,
                                    host=socket.gethostname(),
                                    payload=debug_payload,
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
                            "regime_model_id": classification.regime_model_id,
                            "exchange_ts": exchange_ts.isoformat(),
                            "receipt_ts": tick_receipt_ts.isoformat(),
                            "ts_authority": ts_authority,
                            "ts_source": "binance.rest.ticker_price",
                            "latency_ms": latency_ms,
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
                if prev_ts is not None and tick_ts <= prev_ts:
                    _emit_invariant_violation(
                        event_spine_path,
                        "listener.timestamp_non_monotonic",
                        "warning",
                        {"prev_ts": prev_ts, "now_ts": tick_ts},
                        "timestamps strictly increasing",
                        "ignored",
                    )
            if not heartbeat_gap_violation_emitted:
                for pair in config["pairs"]:
                    last_ts = listener.last_ts_per_pair.get(pair)
                    last_dt = _parse_iso8601(last_ts) if last_ts else None
                    if last_dt is None:
                        last_dt = listener_started_at
                    gap_seconds = (receipt_dt - last_dt).total_seconds()
                    if gap_seconds > 30:
                        _emit_invariant_violation_payload(
                            event_spine_path,
                            "inv-heartbeat-gap-30s",
                            "critical",
                            {"reason": "heartbeat gap exceeded 30s"},
                            timestamp=receipt_ts,
                        )
                        heartbeat_gap_violation_emitted = True
                        break
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        _emit_listener_event(event_spine_path, "listener.stop", {"reason": "keyboard_interrupt"})
        # Emit clean termination for soak observability
        if soak_mode == "OBEY":
            _emit_lifecycle(lifecycle_log, "RUNNER_TERMINATED", soak_id, soak_run_id, reason="keyboard_interrupt")
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
