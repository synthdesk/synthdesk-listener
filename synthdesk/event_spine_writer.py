"""Append-only JSONL spine writer for canonical event envelopes."""

from __future__ import annotations

import json
from pathlib import Path

from synthdesk.event_envelope import EventEnvelope
from synthdesk.event_envelope_validator import validate_event_envelope


def append_event_spine(path: str | Path, event: dict | EventEnvelope) -> None:
    """Append a validated event to a JSONL spine file."""
    validate_event_envelope(event)
    record = vars(event) if isinstance(event, EventEnvelope) else event
    line = json.dumps(record, separators=(",", ":"))
    path = Path(path)
    with path.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(line)
        handle.write("\n")
        handle.flush()
