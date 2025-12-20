"""Canonical synthdesk event envelope (Dec 20 update).

Defines the fixed envelope fields used for all synthdesk events.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    """Data-only container for the canonical synthdesk event envelope."""

    event_id: str
    event_type: str
    timestamp: str
    source: str
    version: str
    host: str
    payload: Any
