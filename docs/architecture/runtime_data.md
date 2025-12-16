---
# Runtime Data (`runs/`)

## Status

The `runs/` directory contains runtime-generated data only.

It is:
- append-only
- non-authoritative
- not required to rebuild the system
- evidence of behavior, not intent

`runs/` is not source code, configuration, or architectural law.

---

## Authority

- Git is not a data store.
- `runs/` must not be committed.
- Loss of `runs/` does not invalidate the system, provided continuity rules are followed.

---

## Continuity Rule (Current)

The current continuity rule is:

- Nightly `rsync` of `runs/` to another machine under operator control.

This rule exists solely to reduce single-disk failure risk.
It does not elevate `runs/` to authoritative system state.

---

## Planned Upgrade

A future upgrade is planned to archive runtime data into immutable object storage
(e.g. S3-compatible storage such as Cloudflare R2).

This upgrade is deferred to avoid premature operational complexity.
---
