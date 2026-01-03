#!/usr/bin/env python3
"""
Replay regime facts from an append-only event spine.

Purpose:
- Acceptance oracle for Phase 1.
- Proves that current regime state is reconstructible from facts alone.

Rules:
- No inference, no thresholds, no defaults.
- Only replay explicit facts in file order.
- Stdlib only.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict


def replay_event_spine(spine_path: Path) -> None:
    current_regime: Dict[str, str] = {}
    last_regime_change: Dict[str, Dict[str, Any]] = {}
    skipped_lines: list[int] = []

    with spine_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                # Skip malformed lines instead of crashing
                skipped_lines.append(line_no)
                print(f"warning: skipping malformed JSON at line {line_no}: {e}", file=sys.stderr)
                continue

            event_type = event.get("event_type")
            payload = event.get("payload")
            ts = event.get("ts") or event.get("timestamp")

            if not isinstance(event_type, str) or not isinstance(payload, dict):
                # ignore malformed or unknown shapes silently
                continue

            if event_type == "market.regime":
                symbol = payload.get("symbol")
                regime = payload.get("regime")

                if isinstance(symbol, str) and isinstance(regime, str):
                    current_regime[symbol] = regime

            elif event_type == "market.regime_change":
                symbol = payload.get("symbol")
                if isinstance(symbol, str):
                    last_regime_change[symbol] = {
                        "from": payload.get("from"),
                        "to": payload.get("to"),
                        "confidence": payload.get("confidence"),
                        "ts": ts,
                    }

            # all other event types are ignored by design

    if skipped_lines:
        print(f"\n=== SKIPPED LINES (malformed JSON) ===")
        print(f"Total skipped: {len(skipped_lines)}")
        if len(skipped_lines) <= 10:
            print(f"Line numbers: {', '.join(map(str, skipped_lines))}")
        else:
            print(f"First 10 line numbers: {', '.join(map(str, skipped_lines[:10]))}")

    print("\n=== CURRENT REGIME PER SYMBOL ===")
    if not current_regime:
        print("(none)")
    else:
        for symbol in sorted(current_regime):
            print(f"{symbol} -> {current_regime[symbol]}")

    print("\n=== LAST REGIME CHANGE PER SYMBOL ===")
    if not last_regime_change:
        print("(none)")
    else:
        for symbol in sorted(last_regime_change):
            change = last_regime_change[symbol]
            print(
                f"{symbol} -> from={change['from']} "
                f"to={change['to']} "
                f"confidence={change['confidence']} "
                f"ts={change['ts']}"
            )


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: replay_regimes.py /path/to/event_spine.jsonl", file=sys.stderr)
        sys.exit(1)

    spine_path = Path(sys.argv[1])
    if not spine_path.exists():
        print(f"file not found: {spine_path}", file=sys.stderr)
        sys.exit(1)

    replay_event_spine(spine_path)


if __name__ == "__main__":
    main()
