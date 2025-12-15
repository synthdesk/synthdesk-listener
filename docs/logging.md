STATUS: REFERENCE (descriptive, non-authoritative)

# Logging surfaces

The listener writes multiple orthogonal log “surfaces” under `runs/<VERSION>/<YYYY-MM-DD>/` to support auditing and offline analysis.

## Raw ingestion

- `prices.csv`: append-only raw observations, one row per pair per poll cycle.
  - Header: `timestamp,pair,price`

## Liveness

- `heartbeat.log`: append-only liveness lines.
  - Format: `<timestamp> alive`

## Tick-level derived logging

- `tick_log.csv`: append-only combined tick record.
  - Includes rolling stats and detector firing flags.
- `detector_trace.csv`: append-only detector firing matrix.
  - Boolean (0/1) indicators per detector per tick.

## Event-level logging

- `events_shadow.csv`: append-only summary log of all emitted events.
  - `metrics_json` stores a JSON-encoded dict of `event["metrics"]`.
- `<timestamp>-<event>.json`: full event payload; name is deduplicated with `_1`, `_2`, ... if needed.

## Integrity logging

- `sequence_integrity.log`: monotonic timestamp violations per pair (one line per violation).
