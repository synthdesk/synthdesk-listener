from __future__ import annotations

from typing import Any, TypedDict


class SourceV1(TypedDict):
    listener_id: str
    schema_id: str


class EnvelopeV1(TypedDict, total=False):
    event_version: int
    event_type: str
    venue: str
    symbol: str
    channel: str
    event_id: int
    seq: int
    ts_event_ns: int
    ts_recv_ns: int
    source: SourceV1
    payload: dict[str, Any]
    payload_raw: dict[str, Any]
