# synthdesk-listener roadmap

This roadmap is intentionally narrow: it tracks correctness, auditability, and research ergonomics for the listener.

## v0.2.x — structured versioning baseline (current)

Delivered:
- Version constant in `synthdesk_listener/version.py`
- Versioned run directories under `runs/<VERSION>/...`
- Normalized detector event schema + `version` field
- `run_meta.json` at startup

Hardening targets:
- Ensure all event JSON writes are atomic (currently CSV/text and some JSON are atomic; event JSON persistence may still be non-atomic).
- Remove legacy `signals_dir` parameter plumbing (kept for backward compatibility).

## v0.3.x — “scientific listener” hardening

Delivered building blocks:
- Heartbeat logging and raw price timeseries (`heartbeat.log`, `prices.csv`)
- Rolling window persistence per pair (`state_<PAIR>.json`)
- Shadow logging surfaces (`events_shadow.csv`, `detector_trace.csv`, `tick_log.csv`)
- Sequence integrity (`tick_id`, monotonicity checks, `sequence_meta.json`)
- Atomic append and atomic JSON write utilities

Remaining cleanup:
- Consolidate documentation of schemas and file contracts (kept in `docs/`).
- Formalize “event file name” constraints and timestamp normalization.

## v0.4 — agency engine (not implemented)

Planned (conceptual, not wired into the listener yet):
- Agent interface that consumes ticks and events
- Offline playback harness using `runs/<...>/tick_log.csv`
- Policy layer for validation/risk constraints

Non-goals for v0.4:
- Live trading execution in this repo
- Exchange credential handling
