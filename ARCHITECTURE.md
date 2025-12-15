STATUS: REFERENCE (descriptive, non-authoritative)

# synthdesk-listener architecture

status: authoritative for v0.4 (signal-only)

This document describes the current architecture as implemented in `synthdesk_listener/` (v0.4).

Scope fence (mandatory):
- This listener is observational only: it records market data and emits signal records for logging and review.
- Detectors are descriptive classifiers (annotations), not strategies.
- Emitted events are inert records; they do not place trades, manage positions, size risk, or interact with capital.
- No detector output implies execution, action, or operational authority.

## Runtime overview

The runtime is a single-process polling loop:

1. Load JSON config and configure logging (`synthdesk_listener/main.py`).
2. Write `runs/<VERSION>/run_meta.json` (startup metadata).
3. Compute the current UTC day directory `runs/<VERSION>/<YYYY-MM-DD>/`.
4. Enter an infinite loop:
   - append a heartbeat line
   - fetch current prices for configured pairs
   - append each price row to `prices.csv`
   - call `PriceListener.process_tick(pair, price, timestamp=now_ts)`
   - sleep `poll_interval_seconds`

## Price ingestion

- The default price source is Binance’s public ticker endpoint.
- `fetch_prices()` returns a dict of `{pair: price}` and skips failures.
- A single ISO timestamp (`now_ts`) is generated per poll cycle and reused for all pairs in that cycle.

## Rolling statistics

Per pair, a `PriceTracker` maintains a bounded `deque` of recent prices and computes:

- `rolling_mean` over an effective window (`min(window, len(history))`)
- `rolling_std` over the same effective window
- `short_vol` and `long_vol` via rolling volatility windows

Startup behavior:
- If the history is too short to compute volatility, `short_vol` and `long_vol` are reported as `0.0` and no exception is raised.

State persistence:
- After each tick, `state_<PAIR>.json` is updated (atomic JSON write) so the rolling window survives restarts.

## Detector pipeline

Each tick runs a fixed sequence of detectors (`synthdesk_listener/listeners/detectors.py`) that classify/annotate the current tick:

- `detect_breakout`: classifies a deviation from rolling mean beyond a configured threshold
- `detect_vol_spike`: classifies a short-term volatility level above the long-term baseline
- `detect_mr_touch`: classifies price outside configured rolling-mean bands

Detectors return either `None` or an event dict with a normalized schema:

- `event`, `pair`, `price`, `timestamp`, `metrics`, `version`

The callback layer overwrites `version` before writing events.

## Event emission

If a detector returns a non-`None` event record, the listener:

- injects `tick_id` into the event dict (global tick sequence)
- merges in the tick’s shared rolling metrics into `event["metrics"]`
- invokes the configured callback for persistence and logging

## Logging surfaces

The system writes multiple orthogonal “surfaces” for auditability:

- `prices.csv`: raw observations
- `tick_log.csv`: full per-tick view (price + metrics + detector indicators)
- `detector_trace.csv`: minimal per-tick detector emission matrix
- `events_shadow.csv`: append-only event summary
- per-event JSON files: full payloads

## Sequence integrity

Sequencing and integrity checks are applied in the listener:

- A global `tick_seq` is incremented on every processed tick and persisted to `runs/<VERSION>/sequence_meta.json`.
- A per-pair monotonicity guard skips non-monotonic timestamps and records violations to `sequence_integrity.log`.
- Emitted events are enriched with `tick_id` so downstream artifacts can be ordered deterministically.

## Atomic persistence

Writes that should remain consistent across abrupt termination are implemented as atomic filesystem operations:

- `atomic_write_json(path, obj)`: write to `*.tmp`, `fsync`, then `replace()`
- `safe_append_text(...)` and `safe_append_csv(...)`: append, flush, and `fsync`

This helps reduce partial-write/corruption likelihood for:
- run metadata
- sequence metadata
- per-pair rolling window state
- append-only CSV/text logs

## NO_SILENT_STRUCTURE

- No new directories, modules, or invariants may be introduced without a same-day ledger entry.
- Unrecorded structures are provisional and deletable.
