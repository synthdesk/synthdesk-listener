"""Report inter-tick time gaps per asset from a tick_observation.jsonl file.

This is a descriptive inspection utility. It does not enforce correctness;
it surfaces gap statistics so downstream aggregation decisions are informed.
"""

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("ts_utc must be a string")
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("ts_utc missing timezone offset")
    return dt.astimezone(timezone.utc)


def _p95(values: list[float]) -> float:
    values = sorted(values)
    idx = max(0, int(math.ceil(0.95 * len(values))) - 1)
    return values[idx]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(
            "Usage: python inspection/assert_tick_gaps.py <tick_observation.jsonl> [threshold_seconds]",
            file=sys.stderr,
        )
        return 1

    path = argv[1]
    threshold = float(argv[2]) if len(argv) == 3 else 20.0

    last_ts: dict[str, datetime] = {}
    gaps: dict[str, list[float]] = defaultdict(list)
    tick_counts: dict[str, int] = defaultdict(int)
    valid = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    asset = rec["asset"]
                    if not isinstance(asset, str):
                        raise TypeError("asset must be a string")
                    ts = _parse_ts(rec["ts_utc"])
                except Exception as exc:
                    print(
                        f"WARNING: skipping malformed line {line_no}: {exc}",
                        file=sys.stderr,
                    )
                    continue

                prev = last_ts.get(asset)
                if prev is not None:
                    gaps[asset].append((ts - prev).total_seconds())
                last_ts[asset] = ts
                tick_counts[asset] += 1
                valid += 1
    except OSError as exc:
        print(f"ERROR: cannot read file: {exc}", file=sys.stderr)
        return 1

    if valid == 0:
        print("ERROR: no valid tick records found", file=sys.stderr)
        return 1

    for asset in sorted(tick_counts):
        g = gaps.get(asset, [])
        max_gap = max(g) if g else None
        p95_gap = _p95(g) if g else None
        over = sum(1 for x in g if x > threshold)

        print(f"asset: {asset}")
        print(f"  total_ticks: {tick_counts[asset]}")
        print(
            f"  max_gap_s: {max_gap:.3f}" if max_gap is not None else "  max_gap_s: n/a"
        )
        print(
            f"  p95_gap_s: {p95_gap:.3f}" if p95_gap is not None else "  p95_gap_s: n/a"
        )
        print(f"  gaps_over_{threshold:g}s: {over}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
