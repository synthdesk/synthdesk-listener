"""Strict validator for the canonical synthdesk EventEnvelope schema."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

from synthdesk.event_envelope import EventEnvelope

EXPECTED_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "source",
    "version",
    "host",
    "payload",
)


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    if "T" not in value:
        raise ValueError("timestamp must be ISO-8601 UTC string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601 UTC string") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be ISO-8601 UTC string")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must be ISO-8601 UTC string")


def validate_event_envelope(value: object) -> None:
    """Validate a dict or EventEnvelope against the canonical schema."""
    if isinstance(value, EventEnvelope):
        field_names = {field.name for field in fields(value)}
        if field_names != set(EXPECTED_FIELDS):
            raise ValueError("event envelope fields do not match canonical schema")
        _validate_timestamp(value.timestamp)
        return

    if isinstance(value, dict):
        for name in EXPECTED_FIELDS:
            if name not in value:
                raise KeyError(f"missing required field: {name}")
        extra = set(value.keys()) - set(EXPECTED_FIELDS)
        if extra:
            raise KeyError(f"unexpected field: {sorted(extra)[0]}")
        _validate_timestamp(value["timestamp"])
        return

    raise TypeError("value must be a dict or EventEnvelope")
