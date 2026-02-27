import pathlib

FORBIDDEN_TOKENS = [
    "ccxt",
    "websocket",
    "asyncio",
    "subprocess",
    "os.system",
    "requests.post",
    "requests.put",
    "requests.delete",
    "web3",
    "eth_account",
    "send_transaction",
]

# Explicit allowlist for runtime plumbing and maintenance utilities that
# intentionally use transport/process primitives.
ALLOWLIST = {
    "synthdesk_listener/cli.py": {"asyncio"},
    "synthdesk_listener/venues/binance/ws.py": {"asyncio", "websocket"},
    "scripts/verify_day.py": {"subprocess"},
    "soak_artifacts/collect_daily.py": {"subprocess"},
    "synthdesk/ops/ledger_cmd.py": {"subprocess"},
}

violations = []

for path in pathlib.Path(".").rglob("*.py"):
    # skip tests, fixtures, and CI helpers
    if any(p in path.parts for p in ("tests", "fixtures", "ci")):
        continue

    text = path.read_text(errors="ignore")
    rel = path.as_posix()
    allowed_tokens = ALLOWLIST.get(rel, set())
    for token in FORBIDDEN_TOKENS:
        if token in allowed_tokens:
            continue
        if token in text:
            violations.append(f"{path}: {token}")

if violations:
    raise SystemExit(
        "forbidden capabilities detected:\n" + "\n".join(violations)
    )
