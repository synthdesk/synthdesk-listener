STATUS: REFERENCE (descriptive, non-authoritative)

---
## fleet quick map

Preferred SSH aliases for the current VPS fleet:

- `synth-a` -> listener / router brain
- `synth-b` -> ingester
- `synth-c` -> research / compute

Use:

```bash
ssh synth-a
ssh synth-b
ssh synth-c
```

Access model is non-root (`lucas` + `sudo`), key-only.

---
## synthdesk-listener

synthdesk-listener is an observational market listener.
it ingests public market data, computes rolling statistics,
and emits inert, auditable classification records.

it does not trade, execute, recommend, optimize, or act.

### what it does
- ingests price and feed data
- maintains ordering and continuity across restarts
- computes descriptive indicators and regime classifications
- emits append-only logs and event records

### what it does not do
- place orders or interact with capital
- manage positions or risk
- make decisions or recommendations
- route, optimize, or adapt behavior

all outputs are descriptive epistemic records.
any downstream system must introduce its own independent logic.
---

## v1 sensor-only path

Sensor-only listeners that emit synthdesk contract v1 envelopes to disk.

Principles:
- no repair
- no window state
- no inference
- write-only
- deterministic envelope mapping

Outputs:
- `/var/lib/synthdesk/raw_v1/venue=binance/symbol=BTCUSDT/channel=aggTrade/date=YYYY-MM-DD.jsonl`
- `/var/lib/synthdesk/raw_v1/venue=binance/symbol=BTCUSDT/channel=depth/date=YYYY-MM-DD.jsonl`
- `/var/lib/synthdesk/raw_v1/venue=binance/symbol=BTCUSDT/channel=bookTicker/date=YYYY-MM-DD.jsonl`

Run:
```
synthdesk-listener aggtrade --symbol BTCUSDT --raw-root /var/lib/synthdesk/raw_v1 --listener-id ingester-b
synthdesk-listener depth --symbol BTCUSDT --interval 100ms --raw-root /var/lib/synthdesk/raw_v1 --listener-id ingester-b
synthdesk-listener bookticker --symbol BTCUSDT --raw-root /var/lib/synthdesk/raw_v1 --listener-id ingester-b
```
