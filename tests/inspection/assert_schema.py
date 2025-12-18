import json
import sys

REQUIRED = {
    "asset": str,
    "ts_utc": str,
    "price": (int, float),
}

path = sys.argv[1]

with open(path) as f:
    for i, line in enumerate(f, 1):
        row = json.loads(line)

        for k, t in REQUIRED.items():
            if k not in row:
                raise AssertionError(f"line {i}: missing field {k}")
            if not isinstance(row[k], t):
                raise AssertionError(
                    f"line {i}: field {k} has type {type(row[k])}"
                )

