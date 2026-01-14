# 7-Day Listener Soak Test

## Purpose

Produce institutional-grade evidence that the listener truth plane is deterministic, stable, and production-ready.

## Quick Start

### Deploy soak test:
```bash
./packages/listener/soak_artifacts/deploy_soak.sh
```

### Check progress (anytime):
```bash
ssh root@157.180.79.228 'cat ~/synthdesk-listener/soak_artifacts/daily_ledger.jsonl | python3 -m json.tool'
```

### Verify completion (after 7 days):
```bash
ssh root@157.180.79.228 'cd ~/synthdesk-listener && python3 soak_artifacts/verify_soak.py'
```

## What Gets Collected

Every day at 00:05 UTC, the system captures:

- **Uptime**: Estimated from tick coverage
- **Events**: Start/stop/crash counts
- **Spine**: Line count, size, deltas
- **Invariants**: Violation counts by type
- **Ticks**: Total processed, max gap observed
- **Disk**: Total usage in bytes
- **Determinism**: SHA256 checksum of replay output (last 1000 ticks)

## Accept Criteria (Phase A Complete)

All must be true:

- ✅ 7 consecutive days of data
- ✅ Uptime ≥ 95% every day
- ✅ Zero crashes
- ✅ Replay checksums valid (determinism proof)
- ✅ Spine growth monotonic
- ✅ Tick gaps < 600s
- ✅ Disk usage < 2GB

## Files

```
soak_artifacts/
├── schema.md              # Artifact spec
├── deploy_soak.sh         # One-command deployment
├── collect_daily.py       # Daily artifact collector (cron)
├── verify_soak.py         # Accept/reject verification
├── README.md              # This file
└── daily_ledger.jsonl     # Append-only artifact log (on VPS)
```

## After Soak Completes

1. Run `verify_soak.py` to check accept criteria
2. If passed → Phase A complete, proceed to Phase B (router)
3. If failed → Fix issues, restart soak

## Anti-Entropy Properties

- **Append-only**: Never mutate past artifacts
- **No narrative**: Only measurable facts
- **Deterministic**: Replay proves emissions are stable
- **Monotonic**: Counts only increase, time only moves forward
- **Verifiable**: Every claim has a checksum or line count
