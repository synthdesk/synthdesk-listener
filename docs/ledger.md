# synthdesk-listener — system ledger

this ledger is append-only.
it records authoritative system state, audits, and decisions.
chat logs are non-authoritative.

---

## 2025-12-16 — state & persistence audit (pass 2)

status: complete  
scope: atomicity, restart behavior, state contracts  

### summary
- no violated contracts observed
- system state consistent as of this date

### robust contracts
- atomic json replace for run_meta.json, sequence_meta.json, state_<pair>.json
- fsync-backed append surfaces for csv/log outputs

### fragile contracts (deferred)
1. startup hard-fail on malformed state_<pair>.json
2. silent tick_seq reset on sequence_meta parse failure
3. non-atomic coinbase jsonl + strict read-before-write scan

### notes
- version-scoped continuity is intentional
- lexicographic timestamp ordering is a relied-upon contract

follow-ups: deferred
