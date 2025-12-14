# synthdesk-listener

`synthdesk-listener` is a research-grade market data listener: it polls spot prices, maintains rolling statistics per trading pair, runs a small detector pipeline, and emits fully logged, versioned artifacts to disk under `runs/`.

## Philosophy

- No black boxes: computations are explicit and inspectable.
- Everything logged: ticks, detector firings, and events are persisted.
- Determinism where possible: per-run directories, stable schemas, and explicit sequencing.
- Auditability first: output is structured for forensic review and offline analysis.

## What this repo is (and is not)

- This repo implements ingestion, rolling metrics, detectors, and persistence.
- Execution / trading, portfolio management, and agentic decision-making are **not implemented** (only stubs/scaffolding exist under `synthdesk/`).

## Quickstart

Prereqs:
- Python 3.10+ recommended
- Network access to Binance public API (for the default price source)

Run with the default config:

```bash
python3 -m synthdesk_listener.main
```

Run with an explicit config path:

```bash
python3 -m synthdesk_listener.main -c synthdesk_listener/config.json
```

Stop with `Ctrl+C`.

## Configuration

Primary config file: `synthdesk_listener/config.json`

Common keys:
- `pairs`: list of symbols (e.g. `["BTCUSDT", "ETHUSDT"]`)
- `poll_interval_seconds`: polling cadence
- `vol_window`: rolling window length for statistics
- `breakout_threshold`: breakout detector threshold (fractional deviation from mean)
- `mr_band_width`: mean-reversion band width (fractional distance from mean)
- `log_level`: logging verbosity
- `log_file`: optional log destination

## Outputs: `runs/<version>/<date>/...`

On startup and during runtime the listener writes a run directory tree rooted at `runs/<VERSION>/`, where `VERSION` comes from `synthdesk_listener/version.py`.

Version-level metadata:
- `runs/<VERSION>/run_meta.json`: start timestamp + config snapshot
- `runs/<VERSION>/sequence_meta.json`: persistent global tick counter (`last_tick_id`)

Daily run artifacts (UTC day):
- `runs/<VERSION>/<YYYY-MM-DD>/heartbeat.log`: append-only liveness markers
- `runs/<VERSION>/<YYYY-MM-DD>/prices.csv`: raw polled prices (`timestamp,pair,price`)
- `runs/<VERSION>/<YYYY-MM-DD>/tick_log.csv`: combined tick view (price + rolling metrics + detector flags)
- `runs/<VERSION>/<YYYY-MM-DD>/detector_trace.csv`: per-tick detector firing flags (0/1)
- `runs/<VERSION>/<YYYY-MM-DD>/events_shadow.csv`: append-only event summary log (CSV)
- `runs/<VERSION>/<YYYY-MM-DD>/<timestamp>-<event>.json`: full event payloads (one file per emitted event)
- `runs/<VERSION>/<YYYY-MM-DD>/state_<PAIR>.json`: per-pair rolling window persistence
- `runs/<VERSION>/<YYYY-MM-DD>/sequence_integrity.log`: monotonic timestamp violations per pair

Notes:
- Timestamps are ISO-8601 UTC strings.
- Events include a `tick_id` field injected by the listener for sequencing.
