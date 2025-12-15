"""Callback utilities for handling detected regime-shift events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from synthdesk.listener.io.atomic import safe_append_csv
from synthdesk.listener.version import VERSION


def handle_regime_shift(event: Dict[str, Any], signals_dir: Path, logger=None) -> Path:
    """Print and persist an event to a versioned run directory.

    Args:
        event: Event payload from detectors.
        signals_dir: Kept for backward compatibility; ignored.
        logger: Optional logger for info/warnings.
    """
    print(event)

    base = Path(__file__).resolve().parents[2] / "runs" / VERSION
    day_dir = base / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    event["version"] = VERSION

    shadow_path = day_dir / "events_shadow.csv"
    header = [
        "timestamp",
        "pair",
        "event",
        "price",
        "version",
        "metrics_json",
    ]
    row = [
        event.get("timestamp"),
        event.get("pair"),
        event.get("event"),
        event.get("price"),
        event.get("version"),
        json.dumps(event.get("metrics", {})),
    ]
    safe_append_csv(shadow_path, row, header=header)

    timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
    event_type = event.get("event", "event")
    filename = day_dir / f"{timestamp}-{event_type}.json"

    # Avoid clobbering existing files if multiple events occur within the same second.
    suffix = 1
    while filename.exists():
        filename = day_dir / f"{timestamp}-{event_type}_{suffix}.json"
        suffix += 1

    with filename.open("w", encoding="utf-8") as handle:
        json.dump(event, handle, indent=2)

    if logger:
        logger.info("Saved event %s to %s", event.get("event"), filename)

    return filename


__all__ = ["handle_regime_shift"]

