# Listener specification

This page specifies the listener’s runtime and data contracts as implemented in `synthdesk_listener/`.

## Inputs

- Config: JSON (`synthdesk_listener/config.json`)
- Price source: polled HTTP endpoint (Binance ticker by default)

## Tick lifecycle

For each poll cycle:

- The runtime computes a single `now_ts` (ISO-8601 UTC).
- For each pair with a price:
  - a row is appended to `prices.csv`
  - `PriceListener.process_tick(pair, price, timestamp=now_ts)` executes:
    - update rolling history/state
    - compute rolling metrics
    - run detectors
    - emit events

## Rolling metrics

Per pair, the listener tracks a bounded rolling history and computes:

- `rolling_mean`
- `rolling_std`
- `short_vol`, `long_vol` (volatility measures)

Constraints:
- Volatility must not raise exceptions during startup / short history. Short histories yield `short_vol=0.0`, `long_vol=0.0`.

## Event schema

Detector output is normalized:

```json
{
  "event": "breakout|vol_spike|mr_touch",
  "pair": "BTCUSDT",
  "price": 123.45,
  "timestamp": "2025-12-14T00:00:00+00:00",
  "metrics": { "...": "..." },
  "version": null
}
```

Listener enrichment:
- Adds `tick_id` (global sequence counter) to all non-`None` events.
- Merges shared rolling metrics into `metrics`.

Callback enrichment:
- Overwrites `event["version"]` with `VERSION` before persistence.
