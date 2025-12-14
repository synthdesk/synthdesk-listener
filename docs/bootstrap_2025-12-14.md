# Bootstrap log — 2025-12-14

This file records the engineering steps taken during the 2025-12-14 build session that bootstrapped the “scientific listener” architecture.

All times approximate due to conversational ordering.

## 00 — repo context

- project folder: `synthdesk-listener/`
- runtime day-run: `runs/<VERSION>/<YYYY-MM-DD>/` (UTC)

This day represents the stabilization of the listener as a research instrument.

## 01 — heartbeat writer

- added `heartbeat.log` writer into the main loop
- confirms listener liveness each poll cycle
- output visible under `runs/<VERSION>/<YYYY-MM-DD>/heartbeat.log`

## 02 — rolling window persistence

- introduced persistent per-pair state files
- implemented `save_state()` and later wrapped it in atomic writes
- ensures rolling metrics survive restarts

## 03 — shadow logging surfaces

### a) `events_shadow.csv`

append-only forensic log for every detected event.

### b) `detector_trace.csv`

binary per-tick matrix of detector firings.

### c) `tick_log.csv`

full union of price, metrics, and firing flags.

## 04 — sequence integrity (a-path)

### a.1 — sequence ids

- added global monotonic tick counter
- events now carry `tick_id`

### a.2 — `sequence_integrity.log`

- logs any non-monotonic timestamps on a per-pair basis
- catches malformed feeds and ordering issues

### a.3 — persistent `sequence_meta.json`

- tick counter survives restarts
- restored during listener init
- guarantees ordering continuity across restarts within the version namespace

## 05 — atomicity (b-path)

### b.1 — atomic JSON writes

- introduced transactional JSON writes (tmp file + `fsync` + rename)
- reduces corruption on abrupt termination

### b.2 — global application of atomic writes

updated persistence for:
- `state_<PAIR>.json`
- `sequence_meta.json`
- `run_meta.json`

the listener becomes crash-resistant for core metadata and state.

## 06 — completion state

the listener is now:
- deterministic
- crash-resilient for core state/logs
- fully logged
- restart-stable
- structured for offline analysis

Next milestone: v0.4 (agency engine), not implemented in this repo.
