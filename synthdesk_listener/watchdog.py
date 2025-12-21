from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from synthdesk.event_envelope import EventEnvelope
from synthdesk.event_spine_writer import append_event_spine
from synthdesk.listener.version import VERSION

DEFAULT_GAP_SECONDS = 300
DEFAULT_POLL_INTERVAL = 5.0


@dataclass(frozen=True)
class _ListenerEvent:
    event_type: str
    timestamp: datetime
    event_id: str


class _OneLineArgParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValueError(message)


def _error_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_last_heartbeat(path: Path) -> Optional[datetime]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        ts = raw.split(" ")[0]
        return _parse_ts(ts)
    return None


def _find_latest_heartbeat(runs_dir: Path) -> tuple[Optional[datetime], Optional[Path], bool]:
    latest = None
    latest_path = None
    heartbeat_files = False
    for heartbeat_path in runs_dir.glob("*/heartbeat.log"):
        heartbeat_files = True
        ts = _read_last_heartbeat(heartbeat_path)
        if ts is None:
            continue
        if latest is None or ts > latest:
            latest = ts
            latest_path = heartbeat_path
    return latest, latest_path, heartbeat_files


def _scan_spine(path: Path) -> tuple[Optional[datetime], Optional[_ListenerEvent]]:
    last_downtime = None
    last_listener_event = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                event_type = obj.get("event_type")
                ts = _parse_ts(obj.get("timestamp"))
                event_id = obj.get("event_id")
                if not isinstance(event_type, str) or ts is None or not isinstance(event_id, str):
                    continue
                if event_type == "listener.downtime":
                    if last_downtime is None or ts > last_downtime:
                        last_downtime = ts
                if event_type in {"listener.start", "listener.stop", "listener.crash"}:
                    if last_listener_event is None or ts > last_listener_event.timestamp:
                        last_listener_event = _ListenerEvent(event_type=event_type, timestamp=ts, event_id=event_id)
    except OSError:
        return None, None
    return last_downtime, last_listener_event


def _emit_downtime(event_spine: Path, payload: dict) -> None:
    event = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type="listener.downtime",
        timestamp=_utc_now().isoformat(),
        source="synthdesk_watchdog",
        version=VERSION,
        host=socket.gethostname(),
        payload=payload,
    )
    try:
        event_spine.parent.mkdir(parents=True, exist_ok=True)
        append_event_spine(event_spine, event)
    except OSError:
        return


def _should_emit_downtime(
    now: datetime,
    last_seen: datetime | None,
    last_downtime: datetime | None,
    gap_seconds: int,
) -> bool:
    if last_seen is None:
        return last_downtime is None
    gap = (now - last_seen).total_seconds()
    if gap <= gap_seconds:
        return False
    if last_downtime and last_seen <= last_downtime:
        return False
    return True


def run_once(event_spine: Path, runs_dir: Path, gap_seconds: int, poll_interval: float) -> bool:
    last_heartbeat, heartbeat_path, heartbeat_files = _find_latest_heartbeat(runs_dir)
    last_downtime, last_listener_event = _scan_spine(event_spine)

    last_seen = last_heartbeat
    if last_listener_event and (last_seen is None or last_listener_event.timestamp > last_seen):
        last_seen = last_listener_event.timestamp

    now = _utc_now()
    if not _should_emit_downtime(now, last_seen, last_downtime, gap_seconds):
        return False

    if last_seen is None:
        reason = "never_seen_alive"
    elif last_listener_event and last_listener_event.event_type in {"listener.stop", "listener.crash"}:
        reason = f"{last_listener_event.event_type}_observed"
    elif last_heartbeat is None:
        reason = "heartbeat_missing" if heartbeat_files else "heartbeat_file_missing"
    else:
        reason = "heartbeat_gap_exceeded"

    payload = {
        "reason": reason,
        "gap_seconds": int((now - last_seen).total_seconds()) if last_seen else None,
        "threshold_seconds": gap_seconds,
        "poll_interval_seconds": poll_interval,
        "last_seen_timestamp": last_seen.isoformat() if last_seen else None,
        "last_heartbeat_timestamp": last_heartbeat.isoformat() if last_heartbeat else None,
        "last_heartbeat_path": str(heartbeat_path) if heartbeat_path else None,
        "last_listener_event_type": last_listener_event.event_type if last_listener_event else None,
        "last_listener_event_timestamp": last_listener_event.timestamp.isoformat() if last_listener_event else None,
        "last_listener_event_id": last_listener_event.event_id if last_listener_event else None,
    }
    _emit_downtime(event_spine, payload)
    return True


def run(
    event_spine: Path,
    runs_dir: Path,
    gap_seconds: int,
    poll_interval: float,
    once: bool,
) -> int:
    if gap_seconds <= 0:
        _error_stderr("error=invalid_gap_seconds detail=gap_seconds_must_be_positive")
        return 2
    poll = max(0.2, float(poll_interval))

    if once:
        emitted = run_once(event_spine, runs_dir, gap_seconds, poll)
        return 0 if emitted else 1

    while True:
        time.sleep(poll)
        run_once(event_spine, runs_dir, gap_seconds, poll)


def cli(argv: Iterable[str] | None = None) -> int:
    parser = _OneLineArgParser(prog="synthdesk_listener.watchdog")
    default_base = Path(__file__).resolve().parents[1] / "runs" / VERSION
    parser.add_argument("--event-spine", default=str(default_base / "event_spine.jsonl"))
    parser.add_argument("--runs-dir", default=str(default_base))
    parser.add_argument("--gap-seconds", type=int, default=DEFAULT_GAP_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--once", action="store_true", help="Emit at most one event and exit.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    return run(
        Path(args.event_spine),
        Path(args.runs_dir),
        int(args.gap_seconds),
        float(args.poll_interval),
        bool(args.once),
    )


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
