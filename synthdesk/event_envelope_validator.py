"""Strict validator for the canonical synthdesk EventEnvelope schema."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

from synthdesk_spine import EventEnvelope, EVENT_ENVELOPE_VERSION

EXPECTED_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "source",
    "version",
    "schema_version",
    "host",
    "payload",
)


def _validate_timestamp_datetime(value: object) -> None:
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware datetime")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be UTC datetime")


def _validate_timestamp_string(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("timestamp must be ISO-8601 UTC string")
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


def _validate_schema_version(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("schema_version must be a string")
    if value != EVENT_ENVELOPE_VERSION:
        raise ValueError("schema_version must match EVENT_ENVELOPE_VERSION")


def validate_event_envelope(value: object) -> None:
    """Validate a dict or EventEnvelope against the canonical schema."""
    if isinstance(value, EventEnvelope):
        field_names = {field.name for field in fields(value)}
        if field_names != set(EXPECTED_FIELDS):
            raise ValueError("event envelope fields do not match canonical schema")
        _validate_timestamp_datetime(value.timestamp)
        _validate_schema_version(value.schema_version)
        return

    if isinstance(value, dict):
        required_fields = [field for field in EXPECTED_FIELDS if field != "schema_version"]
        for name in required_fields:
            if name not in value:
                raise KeyError(f"missing required field: {name}")
        extra = set(value.keys()) - set(EXPECTED_FIELDS)
        if extra:
            raise KeyError(f"unexpected field: {sorted(extra)[0]}")
        _validate_timestamp_string(value["timestamp"])
        if "schema_version" in value:
            _validate_schema_version(value["schema_version"])
        return

    raise TypeError("value must be a dict or EventEnvelope")
