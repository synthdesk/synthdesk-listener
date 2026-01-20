"""Deterministic replay harness for listener regime classification."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from synthdesk.constants import REGIME_EPOCH_START
from synthdesk_spine import EventEnvelope, EVENT_ENVELOPE_VERSION
from synthdesk.event_spine_writer import append_event_spine
from synthdesk.listener.price_listener import PriceListener
from synthdesk.listener.version import VERSION

# Import regime classification from authoritative module
from synthdesk.listener.regime_classifier import (
    RegimeThresholds,
    REGIME_THRESHOLDS_V1,
    REGIME_THRESHOLDS_V2,
    classify_regime,
    classify_regime_full,
    validate_window_config,
)


@dataclass
class ReplaySummary:
    processed: int
    skipped: int
    first_timestamp: Optional[str]
    last_timestamp: Optional[str]
    skipped_lines: list[int]


class ReplayHarness:
    """
    Replay ticks through the listener regime classifier.

    Usage: ReplayHarness(input_path, output_path).run()
    """

    def __init__(self, input_path: Path, output_path: Path, *, vol_window: int = 60) -> None:
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.vol_window = int(vol_window)
        if self.vol_window <= 1:
            raise ValueError("vol_window must be > 1")
        self.window_label = f"{self.vol_window}ticks"

    def run(self) -> ReplaySummary:
        pairs = self._collect_pairs()
        listener = PriceListener(pairs=pairs, vol_window=self.vol_window, logger=None, stateless=True)
        prev_regime_by_symbol: Dict[str, str] = {}
        thresholds = REGIME_THRESHOLDS_V2
        override = os.getenv("SD_Z_DRIFT_THRESHOLD")
        if override:
            try:
                drift_override = float(override)
            except ValueError:
                drift_override = None
            if drift_override is not None:
                thresholds = RegimeThresholds(
                    z_drift_threshold=drift_override,
                    z_high_vol_threshold=REGIME_THRESHOLDS_V2.z_high_vol_threshold,
                    z_breakout_mult=REGIME_THRESHOLDS_V2.z_breakout_mult,
                    window_ticks=REGIME_THRESHOLDS_V2.window_ticks,
                    calibration_window=REGIME_THRESHOLDS_V2.calibration_window,
                    calibration_date=f"{REGIME_THRESHOLDS_V2.calibration_date}_drift{drift_override:.2f}",
                    drift_percentile=f"override:{drift_override:.2f}",
                    high_vol_percentile=REGIME_THRESHOLDS_V2.high_vol_percentile,
                    sample_count=REGIME_THRESHOLDS_V2.sample_count,
                    notes=f"{REGIME_THRESHOLDS_V2.notes} | drift_threshold_override",
                )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("", encoding="utf-8")

        processed = 0
        skipped_lines: list[int] = []
        first_timestamp: Optional[str] = None
        last_timestamp: Optional[str] = None

        with self.input_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                raw = line.strip()
                if not raw:
                    skipped_lines.append(line_no)
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    skipped_lines.append(line_no)
                    continue
                if not isinstance(obj, dict):
                    skipped_lines.append(line_no)
                    continue

                symbol = self._extract_symbol(obj)
                timestamp = self._extract_timestamp(obj)
                raw_timestamp = timestamp
                price = self._extract_price(obj)
                ts_dt = self._parse_timestamp(raw_timestamp)

                if symbol is None or raw_timestamp is None or ts_dt is None or price is None:
                    skipped_lines.append(line_no)
                    continue
                if symbol not in listener.trackers:
                    skipped_lines.append(line_no)
                    continue

                metrics = listener.process_tick(symbol, price, timestamp=raw_timestamp)
                if raw_timestamp >= REGIME_EPOCH_START:
                    regime_metrics = self._build_regime_metrics(metrics, price)
                    classification = classify_regime_full(
                        symbol, regime_metrics, ts_dt.timestamp(), thresholds
                    )
                    regime = classification.regime
                    confidence = classification.confidence

                    regime_payload = {
                        "symbol": symbol,
                        "regime": regime,
                        "confidence": confidence,
                        "window": self.window_label,
                        "thresholds_id": classification.thresholds_id,
                        "window_ticks": thresholds.window_ticks,
                        "metrics": classification.to_payload_metrics(),
                        "tick_ts": raw_timestamp,
                    }
                    self._emit_event("market.regime", raw_timestamp, regime_payload)

                    prev_regime = prev_regime_by_symbol.get(symbol)
                    if prev_regime is None:
                        prev_regime_by_symbol[symbol] = regime
                    elif prev_regime != regime:
                        change_payload = {
                            "symbol": symbol,
                            "from": prev_regime,
                            "to": regime,
                            "confidence": confidence,
                            "window": self.window_label,
                        }
                        self._emit_event("market.regime_change", raw_timestamp, change_payload)
                        prev_regime_by_symbol[symbol] = regime

                if first_timestamp is None:
                    first_timestamp = raw_timestamp
                last_timestamp = raw_timestamp
                processed += 1

        return ReplaySummary(
            processed=processed,
            skipped=len(skipped_lines),
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            skipped_lines=skipped_lines,
        )

    def _collect_pairs(self) -> list[str]:
        pairs: list[str] = []
        seen: set[str] = set()
        with self.input_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                symbol = self._extract_symbol(obj)
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    pairs.append(symbol)
        return pairs

    @staticmethod
    def _extract_symbol(obj: Dict[str, Any]) -> Optional[str]:
        symbol = obj.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            symbol = obj.get("pair")
        if not isinstance(symbol, str) or not symbol:
            symbol = obj.get("asset")
        if not isinstance(symbol, str) or not symbol:
            return None
        return symbol

    @staticmethod
    def _extract_timestamp(obj: Dict[str, Any]) -> Optional[str]:
        timestamp = obj.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            timestamp = obj.get("ts_utc")
        if not isinstance(timestamp, str) or not timestamp:
            timestamp = obj.get("ts")
        if not isinstance(timestamp, str) or not timestamp:
            return None
        return timestamp

    @staticmethod
    def _extract_price(obj: Dict[str, Any]) -> Optional[float]:
        price = obj.get("price")
        if isinstance(price, bool):
            return None
        if isinstance(price, (int, float)):
            return float(price)
        return None

    @staticmethod
    def _parse_timestamp(timestamp: Optional[str]) -> Optional[datetime]:
        if not isinstance(timestamp, str):
            return None
        candidate = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _build_regime_metrics(metrics: object, price: float) -> Dict[str, float]:
        """
        Build regime metrics from PriceTracker output.

        V2: Primary inputs are z-space metrics (z_mean, z_std, ewma_sigma).
        Legacy raw metrics are included for backwards compatibility.
        """
        regime_metrics: Dict[str, float] = {}
        if not isinstance(metrics, dict):
            return regime_metrics

        # Z-space metrics (PRIMARY for V2 classification)
        z_mean = metrics.get("z_mean")
        z_std = metrics.get("z_std")
        ewma_sigma = metrics.get("ewma_sigma")
        z_mean_history = metrics.get("z_mean_history")

        if (
            isinstance(z_mean, (int, float))
            and not isinstance(z_mean, bool)
            and isinstance(z_std, (int, float))
            and not isinstance(z_std, bool)
        ):
            regime_metrics["z_mean"] = float(z_mean)
            regime_metrics["z_std"] = float(z_std)
            if isinstance(ewma_sigma, (int, float)) and not isinstance(ewma_sigma, bool):
                regime_metrics["ewma_sigma"] = float(ewma_sigma)
            if isinstance(z_mean_history, list):
                regime_metrics["z_mean_history"] = z_mean_history

        # Legacy raw metrics (for backwards compatibility and audit)
        returns_mean = metrics.get("rolling_mean")
        returns_std = metrics.get("rolling_std")
        if (
            isinstance(returns_mean, (int, float))
            and not isinstance(returns_mean, bool)
            and isinstance(returns_std, (int, float))
            and not isinstance(returns_std, bool)
        ):
            regime_metrics["returns_mean"] = float(returns_mean)
            regime_metrics["returns_std"] = float(returns_std)

            if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
                range_value = metrics.get("range")
                if isinstance(range_value, (int, float)) and not isinstance(range_value, bool):
                    regime_metrics["range_pct"] = float(range_value) / float(price)

        return regime_metrics

    @staticmethod
    def _normalize_for_hash(obj: Any) -> Any:
        if isinstance(obj, dict):
            normalized: Dict[Any, Any] = {}
            for key in sorted(obj.keys(), key=lambda item: str(item)):
                value = obj[key]
                normalized_key = key if ReplayHarness._is_jsonable(key) else str(key)
                normalized[normalized_key] = ReplayHarness._normalize_for_hash(value)
            return normalized
        if isinstance(obj, (list, tuple)):
            return [ReplayHarness._normalize_for_hash(item) for item in obj]
        if isinstance(obj, float):
            return round(obj, 8)
        if isinstance(obj, (int, str, bool)) or obj is None:
            return obj
        return obj if ReplayHarness._is_jsonable(obj) else str(obj)

    @staticmethod
    def _is_jsonable(obj: Any) -> bool:
        try:
            json.dumps(obj)
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _stable_event_id(event_type: str, timestamp: str, payload: Dict[str, Any]) -> str:
        normalized_payload = ReplayHarness._normalize_for_hash(payload)
        canonical = {"event_type": event_type, "tick_ts": timestamp, "payload": normalized_payload}
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def _emit_event(self, event_type: str, timestamp: str, payload: Dict[str, Any]) -> None:
        # Convert ISO string to timezone-aware datetime
        ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        event = EventEnvelope(
            event_id=self._stable_event_id(event_type, timestamp, payload),
            event_type=event_type,
            timestamp=ts_dt,
            source="synthdesk_listener_replay",
            version=VERSION,
            schema_version=EVENT_ENVELOPE_VERSION,
            host="replay",
            payload=payload,
        )
        append_event_spine(self.output_path, event)


__all__ = ["ReplayHarness", "ReplaySummary"]
