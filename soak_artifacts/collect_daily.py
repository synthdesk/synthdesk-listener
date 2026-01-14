#!/usr/bin/env python3
"""Collect daily soak test artifacts.

Run this at 00:00 UTC each day to capture listener health metrics.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_spine_stats(spine_path: Path) -> dict:
    """Get line count and size of event spine."""
    if not spine_path.exists():
        return {"line_count": 0, "size_bytes": 0}

    line_count = sum(1 for _ in spine_path.open("r"))
    size_bytes = spine_path.stat().st_size

    return {"line_count": line_count, "size_bytes": size_bytes}


def get_invariant_counts(spine_path: Path, date_str: str) -> dict:
    """Count invariant violations by type for given date."""
    counts = {}

    if not spine_path.exists():
        return counts

    with spine_path.open("r") as f:
        for line in f:
            try:
                event = json.loads(line)
                if event.get("event_type") == "invariant.violation":
                    timestamp = event.get("timestamp", "")
                    if timestamp.startswith(date_str):
                        inv_id = event.get("payload", {}).get("invariant_id", "unknown")
                        counts[inv_id] = counts.get(inv_id, 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue

    return counts


def get_listener_events(spine_path: Path, date_str: str) -> dict:
    """Count listener start/stop/crash events for given date."""
    events = {"start": 0, "stop": 0, "crash": 0}

    if not spine_path.exists():
        return events

    with spine_path.open("r") as f:
        for line in f:
            try:
                event = json.loads(line)
                timestamp = event.get("timestamp", "")
                if timestamp.startswith(date_str):
                    event_type = event.get("event_type", "")
                    if event_type == "listener.start":
                        events["start"] += 1
                    elif event_type == "listener.stop":
                        events["stop"] += 1
                    elif event_type == "listener.crash":
                        events["crash"] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    return events


def get_tick_gap_stats(day_dir: Path) -> dict:
    """Get tick gap statistics in seconds."""
    tick_log = day_dir / "tick_observation.jsonl"
    if not tick_log.exists():
        return {"max": 0.0, "p99": 0.0, "p95": 0.0, "median": 0.0}

    timestamps = []
    with tick_log.open("r") as f:
        for line in f:
            try:
                obj = json.loads(line)
                ts_str = obj.get("ts_utc")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    timestamps.append(ts)
            except (json.JSONDecodeError, ValueError):
                continue

    if len(timestamps) < 2:
        return {"max": 0.0, "p99": 0.0, "p95": 0.0, "median": 0.0}

    gaps = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i-1]).total_seconds()
        gaps.append(gap)

    gaps_sorted = sorted(gaps)
    n = len(gaps_sorted)

    return {
        "max": gaps_sorted[-1],
        "p99": gaps_sorted[int(n * 0.99)] if n > 0 else 0.0,
        "p95": gaps_sorted[int(n * 0.95)] if n > 0 else 0.0,
        "median": gaps_sorted[n // 2] if n > 0 else 0.0,
    }


def get_tick_count(day_dir: Path) -> int:
    """Get total number of ticks processed."""
    tick_log = day_dir / "tick_observation.jsonl"
    if not tick_log.exists():
        return 0
    return sum(1 for _ in tick_log.open("r"))


def get_disk_usage(base_dir: Path) -> int:
    """Get total disk usage in bytes."""
    try:
        result = subprocess.run(
            ["du", "-sb", str(base_dir)],
            capture_output=True,
            text=True,
            check=True
        )
        return int(result.stdout.split()[0])
    except (subprocess.CalledProcessError, ValueError):
        return 0


def compute_replay_checksum(day_dir: Path, tail_count: int = 1000) -> str:
    """Replay last N ticks and compute checksum of output."""
    tick_obs = day_dir / "tick_observation.jsonl"
    if not tick_obs.exists():
        return "no_data"

    # Get last N ticks
    with tick_obs.open("r") as f:
        lines = f.readlines()

    if len(lines) < 10:
        return "insufficient_data"

    tail_lines = lines[-tail_count:]

    # Write to temp file
    temp_input = Path("/tmp/soak_replay_input.jsonl")
    temp_output = Path("/tmp/soak_replay_output.jsonl")

    temp_input.write_text("".join(tail_lines))

    # Run replay
    try:
        subprocess.run(
            [
                "python3", "-c",
                "import sys; sys.path.insert(0, 'packages/listener'); "
                "from synthdesk.listener.replay import ReplayHarness; "
                f"ReplayHarness('{temp_input}', '{temp_output}').run()"
            ],
            env={"PYTHONHASHSEED": "0", "PYTHONPATH": "packages/listener"},
            cwd="/root/synthdesk-listener",
            capture_output=True,
            check=True,
            timeout=60
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "replay_failed"

    # Compute checksum
    if not temp_output.exists():
        return "no_output"

    sha256 = hashlib.sha256()
    with temp_output.open("rb") as f:
        sha256.update(f.read())

    return sha256.hexdigest()[:16]


def collect_artifact(
    runs_base: Path,
    artifacts_dir: Path,
    date_str: str,
    prev_artifact: dict | None
) -> dict:
    """Collect all daily metrics."""
    day_dir = runs_base / "0.2.0" / date_str
    spine_path = runs_base / "0.2.0" / "event_spine.jsonl"

    # Current spine stats
    spine_stats = get_spine_stats(spine_path)

    # Deltas
    if prev_artifact:
        spine_line_delta = spine_stats["line_count"] - prev_artifact["spine_line_count"]
        spine_size_delta = spine_stats["size_bytes"] - prev_artifact["spine_size_bytes"]
    else:
        spine_line_delta = spine_stats["line_count"]
        spine_size_delta = spine_stats["size_bytes"]

    # Listener events
    listener_events = get_listener_events(spine_path, date_str)

    # Invariant violations
    invariant_violations = get_invariant_counts(spine_path, date_str)

    # Tick stats
    gap_stats = get_tick_gap_stats(day_dir)
    ticks_processed = get_tick_count(day_dir)

    # Disk usage
    disk_usage = get_disk_usage(runs_base)

    # Replay checksum
    replay_checksum = compute_replay_checksum(day_dir)

    # Uptime (estimate from tick coverage)
    # Assume 10s poll interval, 8640 polls per day ideal
    # Actual uptime ≈ (ticks_processed / 2) / 8640 * 86400
    # Simplified: if we got N ticks in a day, uptime ≈ N/2 * 10 seconds
    uptime_seconds = min(86400, (ticks_processed // 2) * 10)

    # Active pairs (from tick observations)
    pairs_active = []
    tick_obs = day_dir / "tick_observation.jsonl"
    if tick_obs.exists():
        seen_pairs = set()
        with tick_obs.open("r") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    asset = obj.get("asset")
                    if asset:
                        seen_pairs.add(asset)
                except json.JSONDecodeError:
                    continue
        pairs_active = sorted(seen_pairs)

    return {
        "date": date_str,
        "uptime_seconds": uptime_seconds,
        "start_count": listener_events["start"],
        "stop_count": listener_events["stop"],
        "crash_count": listener_events["crash"],
        "spine_line_count": spine_stats["line_count"],
        "spine_size_bytes": spine_stats["size_bytes"],
        "spine_line_delta": spine_line_delta,
        "spine_size_delta": spine_size_delta,
        "invariant_violations": invariant_violations,
        "max_tick_gap_seconds": gap_stats["max"],
        "tick_gap_p99_seconds": gap_stats["p99"],
        "tick_gap_p95_seconds": gap_stats["p95"],
        "tick_gap_median_seconds": gap_stats["median"],
        "disk_usage_bytes": disk_usage,
        "replay_checksum_sha256": replay_checksum,
        "pairs_active": pairs_active,
        "ticks_processed": ticks_processed,
    }


def main() -> int:
    """Main entry point."""
    runs_base = Path("/root/synthdesk-listener/runs")
    artifacts_dir = Path("/root/synthdesk-listener/soak_artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = artifacts_dir / "daily_ledger.jsonl"

    # Get yesterday's date (artifact is for completed day)
    yesterday = datetime.now(timezone.utc).date()
    date_str = yesterday.strftime("%Y-%m-%d")

    # Load previous artifact for deltas
    prev_artifact = None
    if ledger_path.exists():
        with ledger_path.open("r") as f:
            lines = f.readlines()
            if lines:
                try:
                    prev_artifact = json.loads(lines[-1])
                except json.JSONDecodeError:
                    pass

    # Collect artifact
    artifact = collect_artifact(runs_base, artifacts_dir, date_str, prev_artifact)

    # Append to ledger
    with ledger_path.open("a") as f:
        f.write(json.dumps(artifact) + "\n")

    print(f"✓ Artifact collected for {date_str}")
    print(f"  Uptime: {artifact['uptime_seconds']}s")
    print(f"  Ticks: {artifact['ticks_processed']}")
    print(f"  Spine: {artifact['spine_line_count']} lines (+{artifact['spine_line_delta']})")
    print(f"  Replay: {artifact['replay_checksum_sha256']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
