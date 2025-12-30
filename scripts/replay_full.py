#!/usr/bin/env python3
"""Replay ticks through the listener regime classifier.

Usage: replay_full.py <input_jsonl> <output_jsonl>
"""

from __future__ import annotations

import sys
from pathlib import Path

from synthdesk.listener.replay import ReplayHarness


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: replay_full.py <input_jsonl> <output_jsonl>")
        return 2

    input_path = Path(args[0])
    output_path = Path(args[1])

    harness = ReplayHarness(input_path, output_path)
    summary = harness.run()

    print(f"ticks processed: {summary.processed}")
    print(f"lines skipped: {summary.skipped}")
    print(f"first timestamp: {summary.first_timestamp}")
    print(f"last timestamp: {summary.last_timestamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
