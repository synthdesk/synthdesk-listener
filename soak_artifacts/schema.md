# 7-Day Soak Artifact Schema

## Purpose
Produce institution-grade evidence of listener stability, determinism, and operational health over a continuous 7-day period.

## Daily Artifact (append-only)

File: `soak_artifacts/daily_ledger.jsonl`

Each day at 00:00 UTC, append one line:

```json
{
  "date": "2026-01-04",
  "uptime_seconds": 86400,
  "start_count": 1,
  "stop_count": 0,
  "crash_count": 0,
  "spine_line_count": 25431,
  "spine_size_bytes": 12847293,
  "spine_line_delta": 20061,
  "spine_size_delta": 10123847,
  "invariant_violations": {
    "listener.missing_observation": 4691,
    "listener.clock_skew": 0,
    "listener.malformed_tick": 0
  },
  "max_tick_gap_seconds": 302,
  "tick_gap_p99_seconds": 12.4,
  "tick_gap_p95_seconds": 11.8,
  "tick_gap_median_seconds": 10.2,
  "disk_usage_bytes": 15293847,
  "replay_checksum_sha256": "a4b3c2d1e0f9...",
  "pairs_active": ["BTCUSDT", "ETHUSDT"],
  "ticks_processed": 15374
}
```

## Spot-Check Replay (daily)

Every 24 hours, replay the last 1000 ticks and verify:
- Deterministic output (sha256 checksum matches)
- No state drift

## Accept/Reject Criteria

### Accept (Phase A Complete) if ALL true:
- ✅ 7 consecutive days of data
- ✅ Uptime ≥ 95% (no day with uptime < 82000s)
- ✅ Zero crashes
- ✅ Replay checksum stable (spot-check matches every day)
- ✅ Spine growth monotonic (line_count always increases)
- ✅ Max tick gap < 600s (no more than 10 min gap)
- ✅ Disk usage < 2GB total

### Threshold Rationale

- **95% uptime** (82000s/day): Industry standard for Tier 2 availability. Allows ~43min/day for restarts, exchange API outages, and transient network issues.
- **600s max tick gap**: 10-minute tolerance accounts for exchange API rate limiting, temporary outages, and listener restart cycles. Gaps beyond this indicate systemic failure.
- **2GB disk usage**: Based on 7 days @ ~300MB/day nominal growth (tick observations + spine events). Headroom for burst activity without filesystem risk.

### Reject (restart soak) if ANY true:
- ❌ Crash occurs
- ❌ Replay checksum drift detected
- ❌ Tick gap > 600s
- ❌ Invariant violation NOT in expected set
- ❌ Uptime < 95% on any day
- ❌ Spine line count decreases

## Collection Cadence

- **Every 10 minutes**: Health check (process alive, disk usage)
- **Every 24 hours (00:00 UTC)**: Full artifact snapshot + replay spot-check
- **On listener stop/crash**: Emergency artifact capture

## Artifact Storage

```
/root/synthdesk-listener/soak_artifacts/
├── daily_ledger.jsonl          # Append-only daily facts
├── health_checks.jsonl         # 10-min heartbeat log
├── replay_checksums.jsonl      # Daily replay verification
└── emergency_captures/         # Crash dumps, unexpected stops
    └── 2026-01-04T14:23:11Z.json
```

## Anti-Entropy Guarantees

1. **No narrative** - only facts
2. **Append-only** - never mutate past entries
3. **Deterministic** - same inputs → same outputs
4. **Monotonic** - time only moves forward, counts only increase
5. **Verifiable** - every claim has a checksum or line count
