STATUS: REFERENCE (descriptive, non-authoritative)

# History (engineering epochs)

This file tracks the long arc of synthdesk development — conceptual epochs, engineering phases, and major architectural upgrades.

## Epoch 0 — pre-engineering intuition (2024–2025)

- Synthesis of idea: market automation that is layered, scientific, and interpretable.
- Commitment to a hybrid architecture: human agency + mechanical precision + future agentic overlays.
- Early principles:
  - no black boxes
  - everything logged
  - deterministic, traceable behavior
  - modularity for replacing any subsystem
  - future-compatibility with agentic policy engines

## Epoch 1 — listener architecture (Dec 2025)

The project becomes code. The “listener” is born — a continuous, real-time market ingestion and signal-detection engine.

Guiding constraints:
- minimal assumptions
- pure Python for clarity
- scientific logging
- future-proof internal structure

Files established:
- `synthdesk_listener/listeners/price_listener.py`
- `synthdesk_listener/main.py`
- run directory scaffold under `runs/<VERSION>/...`

## Version 0.2.0 — the raw listener

Achievements:
- continuous price ingestion
- rolling windows (mean/std)
- breakout detector
- vol spike detector
- mean-reversion touch detector
- per-tick metrics
- per-event JSON files
- timestamps + monotonicity logic introduced

This establishes the first living “research instrument” inside synthdesk.

## Version 0.3.x — scientific listener (Dec 2025)

### v0.3-step-1 — heartbeat infrastructure

- heartbeat writer added
- `prices.csv` becomes a live timeseries feed
- deterministic daily directories

### v0.3-step-2 — rolling window persistence

- `state_<PAIR>.json` introduced
- listener can restart without losing its statistical state

### v0.3-step-3 — shadow logging

- `events_shadow.csv` created
- `detector_trace.csv` created
- multi-level visibility scaffolding

### v0.3-step-4 — combined tick log

- `tick_log.csv` merges price, metrics, and detector flags

### v0.3-step-a — sequence integrity (a-path)

- deterministic global `tick_id`
- per-pair monotonic timestamp enforcement
- `sequence_integrity.log` added
- persistent `sequence_meta.json` with restore-on-start

This solves correctness and auditability.

### v0.3-step-b — atomicity layer (b-path)

- atomic JSON write utility added
- state writes become crash-resistant
- meta writes become crash-resistant
- project adopts transactional I/O semantics

This solves reliability and resilience.

## Current stance (end of b-path)

synthdesk-listener now provides:

- deterministic sequencing
- monotonicity guarantees
- atomic on-disk persistence
- multi-surface scientific logging
- daily run compartmentalization
- restart stability
- traceability for every tick and every event

## Next epoch — the agency engine (planned)

Planned:
- advisor agent with full access to logs + live feed
- policy exploration layer
- meta-controller for pipeline orchestration
- live simulation harness
- backtest ingestion + synthetic tick-stream generator
