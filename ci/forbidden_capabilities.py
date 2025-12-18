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

violations = []

for path in pathlib.Path(".").rglob("*.py"):
    # skip tests, fixtures, and CI helpers
    if any(p in path.parts for p in ("tests", "fixtures", "ci")):
        continue

    text = path.read_text(errors="ignore")
    for token in FORBIDDEN_TOKENS:
        if token in text:
            violations.append(f"{path}: {token}")

if violations:
    raise SystemExit(
        "forbidden capabilities detected:\n" + "\n".join(violations)
    )
