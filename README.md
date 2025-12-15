STATUS: REFERENCE (descriptive, non-authoritative)

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
