"""
time formatting utilities.
"""

from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()

