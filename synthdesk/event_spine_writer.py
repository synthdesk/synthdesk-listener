"""Append-only JSONL spine writer for canonical event envelopes."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:  # pragma: no cover - platform-specific import
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

from synthdesk_spine import EventEnvelope
from synthdesk.event_envelope_validator import validate_event_envelope


@contextmanager
def _exclusive_lock(handle) -> None:
    if fcntl is None:
        yield
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_event_spine(path: str | Path, event: dict | EventEnvelope) -> None:
    """Append a validated event to a JSONL spine file."""
    validate_event_envelope(event)
    if isinstance(event, EventEnvelope):
        record = vars(event).copy()
        # Convert datetime to ISO string for JSON serialization
        if isinstance(record.get("timestamp"), datetime):
            record["timestamp"] = record["timestamp"].isoformat()
    else:
        record = event
    line = json.dumps(record, separators=(",", ":"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as handle:
        with _exclusive_lock(handle):
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
