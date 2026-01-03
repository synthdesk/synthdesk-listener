# Deploy Listener v0.2.0 to VPS

## Prerequisites

- VPS with systemd (Ubuntu/Debian)
- Python 3.11+
- Git access to synthdesk repo

## Deployment Steps

### 1. Push latest listener code

```bash
# On local machine
cd /Users/lucas/dev/synthdesk/packages/listener

# Commit and push latest changes
git add -A
git commit -m "listener: prepare v0.2.0 for VPS deployment"
git push origin main

# Update parent repo
cd ../..
git add packages/listener
git commit -m "chore: update listener submodule to v0.2.0"
git push origin main
```

### 2. Pull on VPS

```bash
# SSH into VPS
ssh your-vps

# Pull latest code
cd ~/synthdesk  # or wherever your repo lives
git pull
git submodule update --init --recursive

# Or clone fresh if needed:
# git clone --recursive https://github.com/your-user/synthdesk.git
# cd synthdesk
```

### 3. Install listener dependencies

```bash
cd packages/listener

# Install in editable mode
pip3 install -e .

# Verify installation
python3 -m synthdesk_listener.main --help
```

### 4. Configure listener

Edit `config.json` if needed:

```bash
cd packages/listener
cat > config.json <<'EOF'
{
  "poll_interval_seconds": 10,
  "pairs": ["BTCUSDT", "ETHUSDT"],
  "vol_window": 60,
  "log_level": "INFO",
  "log_file": null
}
EOF
```

### 5. Install systemd service

```bash
# Copy service file and customize paths
cd ~/synthdesk/packages/listener

# Edit the service file with your actual paths
export REPO_PATH="$HOME/synthdesk"
export USER="$(whoami)"
export GROUP="$(id -gn)"

sed -e "s|%REPO_PATH%|$REPO_PATH|g" \
    -e "s|%USER%|$USER|g" \
    -e "s|%GROUP%|$GROUP|g" \
    synthdesk-listener.service | sudo tee /etc/systemd/system/synthdesk-listener.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable synthdesk-listener

# Start service
sudo systemctl start synthdesk-listener
```

### 6. Verify it's running

```bash
# Check service status
sudo systemctl status synthdesk-listener

# View live logs
sudo journalctl -u synthdesk-listener -f

# Check event spine is being written
tail -f ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl

# Check for listener.start event
grep '"event_type":"listener.start"' ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl | tail -1
```

## Service Management

```bash
# Stop service
sudo systemctl stop synthdesk-listener

# Restart service
sudo systemctl restart synthdesk-listener

# View logs (last 100 lines)
sudo journalctl -u synthdesk-listener -n 100

# View logs since timestamp
sudo journalctl -u synthdesk-listener --since "2026-01-03 00:00:00"

# Follow logs in real-time
sudo journalctl -u synthdesk-listener -f
```

## Soak Test Monitoring

Once started, monitor for 72h:

```bash
# Check uptime (look for listener.start timestamp)
grep '"event_type":"listener.start"' ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl | tail -1

# Check for crashes
grep '"event_type":"listener.crash"' ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl

# Check for invariant violations
grep '"event_type":"invariant.violation"' ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl

# Monitor spine growth
watch -n 60 'wc -l ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl'

# Check memory usage
ps aux | grep synthdesk_listener
```

## After 72h: Collect Soak Artifacts

```bash
# Stop listener cleanly
sudo systemctl stop synthdesk-listener

# Copy spine to dated snapshot
cp ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl \
   ~/soak_spine_72h_$(date +%Y%m%d).jsonl

# Download to local machine
scp your-vps:~/soak_spine_72h_*.jsonl ./
```

## Troubleshooting

**Service won't start:**
```bash
# Check for Python errors
sudo journalctl -u synthdesk-listener -n 50

# Check config is valid
python3 -c "import json; print(json.load(open('config.json')))"

# Test run manually
cd ~/synthdesk/packages/listener
python3 -m synthdesk_listener.main --config config.json
```

**Listener crashes immediately:**
```bash
# Check event spine for crash details
grep '"event_type":"listener.crash"' ~/synthdesk/packages/listener/runs/0.2.0/event_spine.jsonl | tail -1 | jq
```

## Promotion 1.A: Code Identity Proof

Once soak test passes, capture code provenance:

```bash
# Record commit hash
cd ~/synthdesk/packages/listener
git log -1 --format='%H %s' > soak_code_identity.txt

# Verify no untracked diffs
git status >> soak_code_identity.txt

# Verify binary
which python3 >> soak_code_identity.txt
python3 --version >> soak_code_identity.txt
```

This satisfies LISTENER_PURIFICATION_CHECKLIST.md Promotion 1.A.
