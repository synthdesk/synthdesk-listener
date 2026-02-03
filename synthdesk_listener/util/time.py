from __future__ import annotations

import time


def now_ns() -> int:
    return time.time_ns()


def ms_to_ns(ms: int) -> int:
    return ms * 1_000_000
