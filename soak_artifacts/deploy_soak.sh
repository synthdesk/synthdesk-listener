#!/usr/bin/env bash
# Deploy 7-day soak test with artifact collection to VPS

set -euo pipefail

echo "=== Deploying 7-Day Soak Test ==="
echo

# 1. Upload artifacts infrastructure
echo "→ Uploading artifact collection scripts..."
scp -r packages/listener/soak_artifacts root@157.180.79.228:~/synthdesk-listener/

# 2. Upload updated listener code (determinism fixes)
echo "→ Uploading listener code with determinism fixes..."
ssh root@157.180.79.228 'cd ~/synthdesk-listener && git fetch && git pull'

# 3. Set up cron job for daily artifact collection
echo "→ Setting up daily artifact collection (00:05 UTC)..."
ssh root@157.180.79.228 'bash -s' <<'EOF'
# Add cron job if not exists
CRON_CMD="5 0 * * * cd /root/synthdesk-listener && /usr/bin/python3 soak_artifacts/collect_daily.py >> soak_artifacts/cron.log 2>&1"
(crontab -l 2>/dev/null | grep -F "collect_daily.py" >/dev/null) || (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
echo "✓ Cron job installed"
crontab -l | grep collect_daily
EOF

# 4. Verify listener is running
echo
echo "→ Verifying listener status..."
ssh root@157.180.79.228 'ps aux | grep -E "synthdesk_listener" | grep -v grep || echo "⚠ Listener not running"'

# 5. Create initial artifact baseline
echo
echo "→ Collecting initial baseline artifact..."
ssh root@157.180.79.228 'cd ~/synthdesk-listener && /usr/bin/python3 soak_artifacts/collect_daily.py'

echo
echo "✅ 7-day soak deployment complete"
echo
echo "Next steps:"
echo "  1. Soak runs for 7 days"
echo "  2. Artifacts collected daily at 00:05 UTC"
echo "  3. Check progress: ssh root@157.180.79.228 'cat ~/synthdesk-listener/soak_artifacts/daily_ledger.jsonl'"
echo "  4. After 7 days, verify accept criteria with: python3 soak_artifacts/verify_soak.py"
