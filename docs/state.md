STATUS: LAW (normative, constraining)
VIOLATION CONSEQUENCE: Non-compliant changes must be reverted or blocked until compliant.

# State persistence

The listener persists per-pair rolling windows so it can restart without losing statistical context.

## Per-pair state files

Location:
- `runs/<VERSION>/<YYYY-MM-DD>/state_<PAIR>.json`

Contents:
- `pair`
- `prices`: list of recent prices (rolling history)
- `short_window`, `long_window`

Behavior:
- On startup, if `state_<PAIR>.json` exists, it is loaded into the rolling history.
- On every tick, the state file is overwritten using atomic JSON write.

## Run metadata

Version-level run metadata is written once at startup:
- `runs/<VERSION>/run_meta.json`

This records:
- listener `version`
- `started_at` timestamp
- configured `pairs`
- polling interval and log level
