import json
import sys
from datetime import datetime

last = None
path = sys.argv[1]

with open(path) as f:
    for i, line in enumerate(f, 1):
        row = json.loads(line)
        ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))

        if last and ts <= last:
            raise AssertionError(
                f"line {i}: non-monotonic ts {ts} <= {last}"
            )
        last = ts

