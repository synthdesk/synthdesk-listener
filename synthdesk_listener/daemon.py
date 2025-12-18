from __future__ import annotations

import argparse
import signal
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True)
class DaemonArgs:
    symbols: str
    resolution: str
    output_dir: str
    tick_seconds: int


class _OneLineArgParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValueError(message)


def _error_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _parse_args(argv: Iterable[str] | None) -> DaemonArgs:
    parser = _OneLineArgParser(prog="synthdesk_listener.daemon")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols (passed through)")
    parser.add_argument("--resolution", required=True, help="Resolution (passed through; v0 expects 60s)")
    parser.add_argument("--output-dir", required=True, help="Output directory (passed through)")
    parser.add_argument("--tick-seconds", type=int, default=60, help="Tick cadence in seconds (default: 60)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    tick_seconds = int(args.tick_seconds)
    if tick_seconds <= 0 or tick_seconds % 60 != 0:
        raise ValueError("tick-seconds must be a positive multiple of 60")

    return DaemonArgs(
        symbols=str(args.symbols),
        resolution=str(args.resolution),
        output_dir=str(args.output_dir),
        tick_seconds=tick_seconds,
    )


def _next_full_minute(now: datetime) -> datetime:
    now_utc = now.astimezone(timezone.utc)
    return now_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)


def _sleep_until(target: datetime, shutdown_event: threading.Event) -> bool:
    now = datetime.now(timezone.utc)
    remaining = (target - now).total_seconds()
    if remaining <= 0:
        return True
    return not shutdown_event.wait(timeout=remaining)


def _build_run_argv(args: DaemonArgs) -> list[str]:
    return [
        "--symbols",
        args.symbols,
        "--resolution",
        args.resolution,
        "--output-dir",
        args.output_dir,
    ]


def cli(argv: Iterable[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except ValueError as exc:
        _error_stderr(f"error=invalid_args detail={str(exc).replace(' ', '_')}")
        return 2

    shutdown_event = threading.Event()
    shutdown_reason: dict[str, str] = {"reason": "requested"}

    def _handle_signal(signum: int, _frame: object) -> None:
        shutdown_reason["reason"] = signal.Signals(signum).name
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    next_tick = _next_full_minute(datetime.now(timezone.utc))
    if not _sleep_until(next_tick, shutdown_event):
        _error_stderr(f"shutdown reason={shutdown_reason['reason']}")
        return 0

    from synthdesk_listener import run as run_module

    run_argv = _build_run_argv(args)
    while not shutdown_event.is_set():
        try:
            exit_code = int(run_module.cli(run_argv))
        except Exception as exc:
            _error_stderr(f"tick_failed error=exception detail={str(exc).replace(' ', '_')}")
        else:
            if exit_code != 0:
                _error_stderr(f"tick_failed exit={exit_code}")

        scheduled = next_tick + timedelta(seconds=args.tick_seconds)
        now = datetime.now(timezone.utc)
        if now >= scheduled:
            missed = int((now - scheduled).total_seconds() // args.tick_seconds) + 1
            scheduled = scheduled + timedelta(seconds=missed * args.tick_seconds)
        next_tick = scheduled

        if not _sleep_until(next_tick, shutdown_event):
            break

    _error_stderr(f"shutdown reason={shutdown_reason['reason']}")
    return 0


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
