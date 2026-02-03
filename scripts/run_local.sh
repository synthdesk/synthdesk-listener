#!/usr/bin/env bash
set -euo pipefail

RAW_ROOT="${RAW_ROOT:-/tmp/synthdesk-raw_v1}"
LISTENER_ID="${LISTENER_ID:-local}"
SYMBOL="${SYMBOL:-BTCUSDT}"

python -m synthdesk_listener.cli depth --symbol "$SYMBOL" --interval 100ms --raw-root "$RAW_ROOT" --listener-id "$LISTENER_ID" &
python -m synthdesk_listener.cli aggtrade --symbol "$SYMBOL" --raw-root "$RAW_ROOT" --listener-id "$LISTENER_ID" &

wait
