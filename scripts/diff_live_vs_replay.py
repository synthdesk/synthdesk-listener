#!/usr/bin/env python3
"""Compare live vs replay market.regime events.

Usage: diff_live_vs_replay.py <live_jsonl> <replay_jsonl>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


def _load_regimes(path: Path) -> tuple[Dict[Tuple[str, str], Dict[str, Any]], list[int]]:
    regimes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    skipped_lines: list[int] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                skipped_lines.append(line_no)
                continue
            if not isinstance(obj, dict):
                skipped_lines.append(line_no)
                continue
            if obj.get("event_type") != "market.regime":
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                skipped_lines.append(line_no)
                continue
            timestamp = obj.get("timestamp")
            symbol = payload.get("symbol")
            if not isinstance(timestamp, str) or not isinstance(symbol, str):
                skipped_lines.append(line_no)
                continue
            regimes[(timestamp, symbol)] = {
                "regime": payload.get("regime"),
                "confidence": payload.get("confidence"),
                "window": payload.get("window"),
            }
    return regimes, skipped_lines


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: diff_live_vs_replay.py <live_jsonl> <replay_jsonl>")
        return 2

    live_path = Path(args[0])
    replay_path = Path(args[1])

    live, live_skipped = _load_regimes(live_path)
    replay, replay_skipped = _load_regimes(replay_path)

    mismatches = []
    all_keys = sorted(set(live.keys()) | set(replay.keys()))
    for key in all_keys:
        live_entry = live.get(key)
        replay_entry = replay.get(key)
        if live_entry != replay_entry:
            mismatches.append((key, live_entry, replay_entry))

    print(f"mismatches: {len(mismatches)}")
    if mismatches:
        print("first 20 mismatches:")
        for key, live_entry, replay_entry in mismatches[:20]:
            timestamp, symbol = key
            print(f"- {timestamp} {symbol}")
            print(f"  live: {live_entry}")
            print(f"  replay: {replay_entry}")

    if live_skipped or replay_skipped:
        print(f"skipped lines: live={len(live_skipped)} replay={len(replay_skipped)}")

    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
