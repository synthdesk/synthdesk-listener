STATUS: REFERENCE (descriptive, non-authoritative)

# Sequencing and integrity

Sequencing is treated as a first-class correctness constraint: events and logs should be orderable and auditable even across restarts.

## Global tick counter

- `PriceListener` maintains a global `tick_seq` counter.
- Each processed tick increments the counter and assigns `tick_id`.

Persistence:
- Stored in `runs/<VERSION>/sequence_meta.json` as:
  - `last_tick_id`
  - `updated_at`

This allows `tick_id` continuity across process restarts within the same version namespace.

## Per-pair monotonic timestamp enforcement

The listener enforces per-pair monotonicity:

- If a tick arrives with `timestamp <= last_timestamp_for_pair`, it is rejected.
- The rejection is logged to `sequence_integrity.log` and the tick produces no events.

## Event ordering

All emitted events include:
- `tick_id`
- `timestamp` (ISO-8601 UTC)

Downstream consumers can sort by `(tick_id, timestamp, pair)` to produce a deterministic ordering.
