STATUS: LAW (normative, constraining)
VIOLATION CONSEQUENCE: Non-compliant changes must be reverted or blocked until compliant.

This file is the authoritative entrypoint for synthdesk-listener invariants. It anchors the non-negotiable constraints that govern emitted artifacts, persistence, and boundary discipline. In any conflict, defer to the canonical LAW documents listed below.

## Non-Negotiable Principles

- Outputs MUST remain descriptive epistemic records.
- Outputs MUST NOT encode recommendations, priorities, timing, magnitude, or intent.
- Outputs MUST NOT introduce advisory/execution semantics (forbidden vocabulary is defined in the semantics LAW).
- Downstream systems MUST introduce their own independent decision logic; listener artifacts confer no operational authority.
- The listener MUST emit only raw observations plus belief-free scalar metrics: `log_return`, `rolling_mean`, `rolling_std` (volatility), `zscore`, `slope`, `range`, `rolling_correlation`.
- Detectors MUST NOT execute in the listener; detector execution MUST be relocated to `synthdesk_agency/` consuming listener outputs (detector logic unchanged for now, and existing detectors must not be removed or deprecated).
- Persistence MUST be treated as correctness: core JSON state/metadata MUST be written transactionally (tmp + fsync + replace).
- Append-only log surfaces MUST flush and fsync on each write.
- Per-pair rolling state MUST persist under `runs/<VERSION>/<YYYY-MM-DD>/state_<PAIR>.json` and MUST be reloaded when present.
- Version-level run metadata MUST be written to `runs/<VERSION>/run_meta.json`.
- Namespace boundaries MUST be respected: `synthdesk_listener/` may import `synthdesk/`; `synthdesk_agency/` MUST NOT import from listener namespaces.
- New top-level namespaces or invariants MUST NOT be introduced silently; they MUST be explicitly classified, recorded, and ledgered.

## Scope Fence

The listener MUST NOT:

- decide, recommend, choose, select, route, optimize, act, trigger, or execute
- enter/exit, buy/sell, size/scale, increase/reduce exposure, or otherwise express action
- emit artifacts implying strategy, trade, position, order, risk, pnl/profit/loss, edge/alpha, or opportunity/setup

## Canonical Law Documents

- `docs/semantics.md`
- `docs/atomicity.md`
- `docs/state.md`
- `docs/architecture/listener_boundary.md`
- `docs/architecture/runtime_data.md` (TODO: clarify `STATUS:`; currently unmarked)
