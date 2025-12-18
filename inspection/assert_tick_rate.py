"""Report per-asset tick rate statistics from a tick_observation.jsonl file.

Ticks are bucketed by (asset, minute), where the minute is ts_utc floored to
the minute in UTC.
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


def _p95_int(values: list[int]) -> int:
    values = sorted(values)
    idx = max(0, int(math.ceil(0.95 * len(values))) - 1)
    return values[idx]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "Usage: python inspection/assert_tick_rate.py <tick_observation.jsonl>",
            file=sys.stderr,
        )
        return 1

    path = argv[1]
    per_asset_minute: dict[str, dict[datetime, int]] = defaultdict(
        lambda: defaultdict(int)
    )
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

                minute = ts.replace(second=0, microsecond=0)
                per_asset_minute[asset][minute] += 1
                valid += 1
    except OSError as exc:
        print(f"ERROR: cannot read file: {exc}", file=sys.stderr)
        return 1

    if valid == 0:
        print("ERROR: no valid tick records found", file=sys.stderr)
        return 1

    for asset in sorted(per_asset_minute):
        counts = list(per_asset_minute[asset].values())
        minutes = len(counts)
        total = sum(counts)
        mean = total / minutes

        print(f"asset: {asset}")
        print(f"  minutes_observed: {minutes}")
        print(f"  mean_ticks_per_minute: {mean:.3f}")
        print(f"  min_ticks_per_minute: {min(counts)}")
        print(f"  max_ticks_per_minute: {max(counts)}")
        print(f"  p95_ticks_per_minute: {_p95_int(counts)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
