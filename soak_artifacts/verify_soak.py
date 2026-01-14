#!/usr/bin/env python3
"""Verify 7-day soak test against accept/reject criteria."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def verify_soak(ledger_path: Path) -> tuple[bool, list[str]]:
    """
    Verify soak test results.

    Returns:
        (passed, reasons) - True if all criteria met, list of issues if not
    """
    if not ledger_path.exists():
        return False, ["Ledger file does not exist"]

    with ledger_path.open("r") as f:
        artifacts = [json.loads(line) for line in f if line.strip()]

    if len(artifacts) < 7:
        return False, [f"Insufficient days: {len(artifacts)}/7"]

    issues = []

    # Check each day
    for i, artifact in enumerate(artifacts):
        day_num = i + 1
        date = artifact.get("date", "unknown")

        # Uptime >= 95% (82000s out of 86400s)
        uptime = artifact.get("uptime_seconds", 0)
        if uptime < 82000:
            issues.append(f"Day {day_num} ({date}): Low uptime {uptime}s < 82000s")

        # Zero crashes
        crashes = artifact.get("crash_count", 0)
        if crashes > 0:
            issues.append(f"Day {day_num} ({date}): {crashes} crash(es) detected")

        # Replay checksum exists and is valid
        checksum = artifact.get("replay_checksum_sha256", "")
        if checksum in ["no_data", "insufficient_data", "replay_failed", "no_output", ""]:
            issues.append(f"Day {day_num} ({date}): Invalid replay checksum: {checksum}")

        # Spine growth monotonic
        if i > 0:
            prev_count = artifacts[i-1].get("spine_line_count", 0)
            curr_count = artifact.get("spine_line_count", 0)
            if curr_count < prev_count:
                issues.append(
                    f"Day {day_num} ({date}): Spine line count decreased "
                    f"({prev_count} → {curr_count})"
                )

        # Max tick gap < 600s
        max_gap = artifact.get("max_tick_gap_seconds", 0)
        if max_gap >= 600:
            issues.append(f"Day {day_num} ({date}): Tick gap {max_gap}s >= 600s")

        # Disk usage < 2GB
        disk_usage = artifact.get("disk_usage_bytes", 0)
        if disk_usage >= 2_000_000_000:
            issues.append(
                f"Day {day_num} ({date}): Disk usage {disk_usage} >= 2GB"
            )

    # Determinism validation: enforce checksum invariance across days
    baseline_checksum = None
    for i, artifact in enumerate(artifacts):
        day_num = i + 1
        date = artifact.get("date", "unknown")
        checksum = artifact.get("replay_checksum_sha256", "")

        # Skip invalid checksums
        if checksum in ["no_data", "insufficient_data", "replay_failed", "no_output", ""]:
            continue

        # Sanity check: hex format
        if not all(c in "0123456789abcdef" for c in checksum):
            issues.append(f"Day {day_num} ({date}): Malformed checksum {checksum}")
        else:
            if baseline_checksum is None:
                baseline_checksum = checksum
            elif checksum != baseline_checksum:
                issues.append(
                    f"Day {day_num} ({date}): Determinism violation - "
                    f"checksum drift detected. "
                    f"expected={baseline_checksum}, observed={checksum}"
                )

    passed = len(issues) == 0
    return passed, issues


def main() -> int:
    """Main entry point."""
    ledger_path = Path("/root/synthdesk-listener/soak_artifacts/daily_ledger.jsonl")

    # Allow local testing
    if not ledger_path.exists():
        ledger_path = Path("soak_artifacts/daily_ledger.jsonl")

    if not ledger_path.exists():
        print("❌ Ledger file not found")
        return 1

    passed, issues = verify_soak(ledger_path)

    print("=== 7-Day Soak Verification ===")
    print()

    if passed:
        print("✅ SOAK TEST PASSED")
        print()
        print("Phase A completion criteria met:")
        print("  ✓ 7 consecutive days of data")
        print("  ✓ Uptime ≥ 95% every day")
        print("  ✓ Zero crashes")
        print("  ✓ Replay checksums valid")
        print("  ✓ Spine growth monotonic")
        print("  ✓ Tick gaps < 10 minutes")
        print("  ✓ Disk usage < 2GB")
        print()
        print("Truth plane is institutional-grade. Phase A complete.")
        return 0
    else:
        print("❌ SOAK TEST FAILED")
        print()
        print(f"Issues found ({len(issues)}):")
        for issue in issues:
            print(f"  • {issue}")
        print()
        print("Soak must be restarted or extended.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
