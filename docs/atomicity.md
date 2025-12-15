STATUS: LAW (normative, constraining)
VIOLATION CONSEQUENCE: Non-compliant changes must be reverted or blocked until compliant.

# Atomicity and crash-safety

The listener treats disk persistence as part of correctness: partially written state can corrupt research datasets and invalidate audit trails.

## Atomic JSON writes

`atomic_write_json(path, obj)` writes JSON transactionally:

1. write to a temporary `*.tmp` sibling file
2. flush + `fsync`
3. atomically replace the destination path

Used for:
- `run_meta.json`
- `sequence_meta.json`
- `state_<PAIR>.json`

## Safe append for text/CSV

Append-only logs use flush + `fsync` after each row/line:

- `safe_append_text(path, line)`
- `safe_append_csv(path, row, header=...)`

Used for:
- `heartbeat.log`
- `prices.csv`
- `tick_log.csv`
- `detector_trace.csv`
- `events_shadow.csv`
- `sequence_integrity.log`

Rationale:
- Append-only logs are resilient by construction, but explicit `fsync` reduces loss in the face of abrupt power/process death.
