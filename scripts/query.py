#!/usr/bin/env python3
"""Read-only query tool for synthdesk event artifacts.

Golden corpus locked. Do not extend.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone

from synthdesk.event_envelope_validator import validate_event_envelope


def _die(code: int, message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _parse_timestamp(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate)


def _parse_duration(value: str) -> timedelta:
    if value != "24h":
        raise ValueError("only --last 24h is supported in this build")
    return timedelta(hours=24)


def _load_spine(path: str) -> list[tuple[dict, datetime]]:
    events: list[tuple[dict, datetime]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.rstrip("\n")
                if not line:
                    _die(2, f"input parse error: empty line at {line_no}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    _die(2, f"input parse error: {exc.msg} at line {line_no}")
                try:
                    validate_event_envelope(record)
                except Exception as exc:  # pragma: no cover - error path
                    _die(3, f"schema validation error: {exc}")
                try:
                    timestamp = _parse_timestamp(record["timestamp"])
                except Exception as exc:  # pragma: no cover - error path
                    _die(3, f"schema validation error: {exc}")
                events.append((record, timestamp))
    except FileNotFoundError:
        _die(2, f"input parse error: missing file: {path}")
    return events


def _get_nested(record: dict, path: str):
    """Navigate dot-notation path in record. Returns None if path doesn't exist."""
    parts = path.split(".")
    current = record
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return None
        else:
            return None
    return current


def _parse_where(expr: str) -> tuple[str, str, str]:
    """Parse where expression into (path, operator, value)."""
    # Check multi-char operators first to avoid incorrect splits
    for op in [">=", "<=", "==", "!=", ">", "<", "="]:
        if op in expr:
            parts = expr.split(op, 1)
            if len(parts) == 2:
                return parts[0].strip(), op, parts[1].strip()
    raise ValueError(f"invalid where expression: {expr}")


def _evaluate_where(record: dict, path: str, operator: str, value_str: str) -> bool:
    """Evaluate where clause against record."""
    actual = _get_nested(record, path)
    if actual is None:
        return False

    # Try numeric comparison first
    try:
        actual_num = float(actual)
        value_num = float(value_str)
        if operator == ">":
            return actual_num > value_num
        elif operator == "<":
            return actual_num < value_num
        elif operator == ">=":
            return actual_num >= value_num
        elif operator == "<=":
            return actual_num <= value_num
        elif operator in ("==", "="):
            return actual_num == value_num
        elif operator == "!=":
            return actual_num != value_num
    except (ValueError, TypeError):
        # Fall back to string comparison
        if operator in ("==", "="):
            return str(actual) == value_str
        elif operator == "!=":
            return str(actual) != value_str
        # Other operators not supported for strings
        return False
    return False


def _load_legacy_jsonl(path: str) -> list[dict]:
    """Load legacy JSONL (no envelope validation)."""
    records: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.rstrip("\n")
                if not line:
                    _die(2, f"input parse error: empty line at {line_no}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    _die(2, f"input parse error: {exc.msg} at line {line_no}")
                records.append(record)
    except FileNotFoundError:
        _die(2, f"input parse error: missing file: {path}")
    return records


def _load_csv(path: str) -> list[dict]:
    """Load CSV with header. Values are kept as strings."""
    records: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                records.append(dict(row))
    except FileNotFoundError:
        _die(2, f"input parse error: missing file: {path}")
    except csv.Error as exc:
        _die(2, f"input parse error: {exc}")
    return records


def _project(record: dict) -> dict:
    fields = ("timestamp", "event_type", "source", "payload")
    return {field: record.get(field) for field in fields}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="query.py")
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--spine")
    sources.add_argument("--ticks")
    sources.add_argument("--csv")
    parser.add_argument("--last")
    parser.add_argument("--event-type")
    parser.add_argument("--where")
    parser.add_argument("--group-by")
    parser.add_argument("--agg")
    parser.add_argument("--format", default="table")
    parser.add_argument("--from", dest="from_ts")
    parser.add_argument("--to", dest="to_ts")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _die(1, f"invalid arguments: {' '.join(unknown)}")

    if args.from_ts or args.to_ts:
        _die(1, "--from/--to are not supported in this build")
    if args.format != "json":
        _die(1, "only --format json is supported in this build")

    # Branch on mode: spine vs legacy
    if args.spine:
        # Spine pipeline
        if args.last:
            try:
                duration = _parse_duration(args.last)
            except ValueError as exc:
                _die(1, str(exc))

        events = _load_spine(args.spine)

        # Step 1: Time filtering (if --last provided)
        if args.last:
            if events:
                latest_ts = max(ts for _, ts in events)
                start_of_day = latest_ts.astimezone(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                events = [(record, ts) for record, ts in events if ts >= start_of_day]

        # Step 2: Event-type filtering (if --event-type provided)
        if args.event_type:
            events = [(record, ts) for record, ts in events
                      if record.get("event_type") == args.event_type]

        # Step 3: Where filtering (if --where provided)
        if args.where:
            try:
                path, operator, value = _parse_where(args.where)
            except ValueError as exc:
                _die(1, str(exc))
            events = [(record, ts) for record, ts in events
                      if _evaluate_where(record, path, operator, value)]

        filtered = [record for record, ts in events]
        is_spine = True

    elif args.ticks:
        # Legacy ticks pipeline
        if args.last:
            _die(1, "--last is not supported for --ticks")
        if args.event_type:
            _die(1, "--event-type is not supported for --ticks")

        records = _load_legacy_jsonl(args.ticks)

        # Where filtering only
        if args.where:
            try:
                path, operator, value = _parse_where(args.where)
            except ValueError as exc:
                _die(1, str(exc))
            records = [record for record in records
                      if _evaluate_where(record, path, operator, value)]

        filtered = records
        is_spine = False

    elif args.csv:
        # CSV pipeline
        if args.last:
            _die(1, "--last is not supported for --csv")
        if args.event_type:
            _die(1, "--event-type is not supported for --csv")
        if args.group_by or args.agg:
            _die(1, "--group-by/--agg is not supported for --csv in this build")

        records = _load_csv(args.csv)

        # Where filtering only
        if args.where:
            try:
                path, operator, value = _parse_where(args.where)
            except ValueError as exc:
                _die(1, str(exc))
            records = [record for record in records
                      if _evaluate_where(record, path, operator, value)]

        filtered = records
        is_spine = False

    else:
        _die(1, "no input source specified")

    # Step 4: Aggregation (if --group-by and --agg provided)
    if args.group_by and args.agg:
        if args.agg != "count":
            _die(1, f"only --agg count is supported in this build")

        # Group by the specified path
        groups: dict[str, int] = {}
        for record in filtered:
            group_value = _get_nested(record, args.group_by)
            if group_value is not None:
                key = str(group_value)
                groups[key] = groups.get(key, 0) + 1

        # Sort by key for deterministic output
        rows = [{args.group_by: k, "count": v} for k, v in sorted(groups.items())]
    else:
        # Normal projection
        if is_spine:
            rows = [_project(record) for record in filtered]
        else:
            # Legacy mode: return all fields as-is
            rows = filtered

    sys.stdout.write(json.dumps(rows, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
