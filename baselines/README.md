# Regime Determinism Baselines

This directory contains post-epoch baselines for SynthDesk regime determinism.

## Regime Epoch

All regime determinism guarantees apply **only after**:

REGIME_EPOCH_START = 2025-12-30T07:09:28.445034+00:00

Any `market.regime` or `market.regime_change` events before this timestamp are
considered legacy observational artifacts and are intentionally excluded from
replay and strict diffing.

## Why This Exists

Before the epoch:
- regime emission was incomplete
- tick timestamps were not canonical
- replay parity was undefined

After the epoch:
- live and replay share the same tick semantics
- regime classification is deterministic
- strict diff is meaningful

Do not attempt to "fix" or backfill pre-epoch data.
If strict diff fails post-epoch, it is a real bug.
