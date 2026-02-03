from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RotatorKey:
    raw_root: str
    venue: str
    symbol: str
    channel: str


class JsonlDailyRotator:
    """
    Daily jsonl writer:
      <raw_root>/venue=<venue>/symbol=<symbol>/channel=<channel>/date=YYYY-MM-DD.jsonl

    Guarantees:
    - append-only
    - flush on each write (safe baseline; can be relaxed later if desired)
    """

    def __init__(self, *, raw_root: str, venue: str, symbol: str, channel: str) -> None:
        self.key = RotatorKey(raw_root=raw_root, venue=venue, symbol=symbol, channel=channel)
        self._fh = None
        self._current_date = None

    def _date_utc(self, ts_recv_ns: int) -> str:
        dt = datetime.fromtimestamp(ts_recv_ns / 1e9, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    def _path_for_date(self, date_yyyy_mm_dd: str) -> Path:
        base = Path(self.key.raw_root)
        return (
            base
            / f"venue={self.key.venue}"
            / f"symbol={self.key.symbol}"
            / f"channel={self.key.channel}"
            / f"date={date_yyyy_mm_dd}.jsonl"
        )

    def _ensure_open(self, date_yyyy_mm_dd: str) -> None:
        if self._fh is not None and self._current_date == date_yyyy_mm_dd:
            return
        self.close()
        path = self._path_for_date(date_yyyy_mm_dd)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8", buffering=1)
        self._current_date = date_yyyy_mm_dd

    def write(self, obj: dict[str, Any]) -> None:
        ts_recv_ns = int(obj["ts_recv_ns"])
        date = self._date_utc(ts_recv_ns)
        self._ensure_open(date)
        assert self._fh is not None
        self._fh.write(json.dumps(obj, separators=(",", ":"), sort_keys=True))
        self._fh.write("\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.flush()
            finally:
                try:
                    self._fh.close()
                finally:
                    self._fh = None
                    self._current_date = None
