---
# Listener Namespace Boundary

## Purpose

This document defines the canonical boundary between listener-related namespaces
in the SynthDesk system. It is authoritative.

The goal is to prevent ambiguity, accidental coupling, and silent architectural drift.

---

## Canonical Namespaces

### 1. synthdesk_listener/

**Role:** Runtime listener (operational shell)

Contains:
- daemons
- price listeners
- callbacks
- transforms
- runtime wiring

Characteristics:
- long-running
- stateful
- operational
- allowed to touch the filesystem under `runs/`

Rules:
- may import from `synthdesk/`
- must not be imported by `synthdesk_agency/`

---

### 2. synthdesk/listener/

**Role:** Pure listener logic (stateless primitives)

Contains:
- detectors
- IO primitives
- state loaders / savers
- reusable logic

Characteristics:
- stateless or explicitly scoped state
- deterministic
- reusable
- testable in isolation

Rules:
- may be imported by `synthdesk_listener/`
- must not be imported by `synthdesk_agency/`

---

### 3. synthdesk_agency/

**Role:** Advisory evaluation engine

Rules:
- must not import from either listener namespace
- interacts with listener output only via:
  - adapters
  - snapshots
  - JSON / files
- has no execution or operational authority

---

## Import Direction (Summary)

Allowed:
- synthdesk_listener → synthdesk
- synthdesk_agency → adapters / files only

Forbidden:
- synthdesk_agency → synthdesk_listener
- synthdesk_agency → synthdesk/listener
- cross-imports that bypass adapters

---

## No-Silent-Structure Rule

Any new top-level package or namespace must be:
1. Explicitly classified (runtime / logic / advisory / other)
2. Recorded in architecture documentation
3. Referenced in the daily ledger

Unclassified structure is provisional and may be deleted without notice.

---

## Status

This boundary is locked as architectural law.
---
