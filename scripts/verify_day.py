#!/usr/bin/env python3
"""Daily determinism verification wrapper.

Usage: verify_day.py <day_dir>
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def _error(message: str) -> int:
    print(message)
    return 2


def _find_event_spine(day_dir: Path) -> Path | None:
    candidates = [
        day_dir / "event_spine.jsonl",
        day_dir.parent / "event_spine.jsonl",
        day_dir.parent.parent / "event_spine.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return _error("usage: verify_day.py <day_dir>")

    day_dir = Path(args[0])
    if not day_dir.exists() or not day_dir.is_dir():
        return _error(f"error=invalid_day_dir path={day_dir}")

    tick_path = day_dir / "tick_observation.jsonl"
    if not tick_path.exists() or not tick_path.is_file():
        return _error(f"error=missing_tick_observation path={tick_path}")

    event_spine = _find_event_spine(day_dir)
    if event_spine is None:
        return _error("error=missing_event_spine")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="replay_", suffix=".jsonl", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        replay_cmd = [
            sys.executable,
            "-m",
            "scripts.replay_full",
            str(tick_path),
            str(temp_path),
        ]
        replay_result = subprocess.run(replay_cmd, check=False)
        if replay_result.returncode != 0:
            return _error("error=replay_failed")

        if not temp_path.exists() or temp_path.stat().st_size == 0:
            return _error("error=empty_replay_output")

        diff_cmd = [
            sys.executable,
            "-m",
            "scripts.diff_live_vs_replay",
            "--mode",
            "strict",
            "--compare-event-id",
            str(event_spine),
            str(temp_path),
        ]
        diff_result = subprocess.run(diff_cmd, check=False)
        if diff_result.returncode == 0:
            print("PASS")
            return 0
        if diff_result.returncode == 1:
            print("ERROR: listener behavior diverged from frozen regime epoch")
            sys.exit(1)
        return _error("error=diff_failed")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
