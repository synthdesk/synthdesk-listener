# query.py

**Read-only query tool for synthdesk event artifacts.**

## Purpose

`query.py` is a deterministic lens over event data. It does not analyze, enrich, or infer. It filters, projects, and aggregates exactly as specified.

## Supported Formats

- **Spine**: Canonical event envelope (validated)
- **Ticks**: Legacy JSONL (flat schema)
- **CSV**: Header-based tabular data

## Capabilities

### Filtering
- `--last 24h`: Time filter (start of UTC day, spine only)
- `--event-type TYPE`: Event type filter (spine only)
- `--where EXPR`: Dot-notation predicates with numeric coercion

### Aggregation
- `--group-by PATH --agg count`: Count by group (spine only)

### Output
- `--format json`: Compact JSON array (only supported format in v1)

## What This Tool Is Not

- Not an analytics engine
- Not a dashboard
- Not a join/merge tool
- Not a streaming processor
- Not extensible

## Golden Corpus

All behavior is locked by golden tests in `tests/golden/`:
- 01: spine + last 24h
- 02: spine + event-type filter
- 03: spine + where filter
- 04: spine + aggregation count
- 05: legacy ticks basic
- 06: legacy csv basic

**Do not modify behavior without updating golden tests.**

## Usage Examples

```bash
# Spine: last 24h regime events
query.py --spine events.jsonl --last 24h --event-type market.regime --format json

# Spine: high-confidence regimes
query.py --spine events.jsonl --event-type market.regime --where 'payload.confidence>0.7' --format json

# Spine: regime distribution
query.py --spine events.jsonl --event-type market.regime --group-by payload.regime --agg count --format json

# Legacy ticks: filter by asset
query.py --ticks ticks.jsonl --where asset=BTCUSDT --format json

# CSV: numeric filter with string output
query.py --csv data.csv --where 'zscore>0' --format json
```

## Design Principles

1. **Deterministic**: Same input → same output, always
2. **Read-only**: Never modifies source files
3. **Schema-respecting**: Validates spine, preserves legacy formats
4. **Fail-closed**: Invalid flags error immediately
5. **Mode-isolated**: Spine/ticks/CSV pipelines don't leak

## Extension Policy

**This tool is frozen at v1.**

For new capabilities:
- Joins → separate tool
- Multi-condition where → separate tool
- Streaming → separate tool
- Inference/enrichment → agency layer

This is a boundary, not a platform.
