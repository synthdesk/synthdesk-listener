"""
Ledger synthesis + append-only persistence.

Intent: compress daily inputs into an authoritative, append-only memory artifact
(`synthdesk/ledger.md`). This module does not interpret, plan, or recommend.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _default_ledger_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ledger.md"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def append_synthesized_ledger(
    git_diff: str,
    notes: str,
    state: str,
    *,
    ledger_path: Optional[Path] = None,
) -> bool:
    """
    Call the AI airlock to synthesize a ledger entry, then append it to `ledger.md`.

    - Never overwrites existing ledger contents.
    - AI failures are swallowed (ledger append is best-effort).
    """

    path = Path(ledger_path) if ledger_path is not None else _default_ledger_path()

    try:
        from synthdesk.ai.wrapper import synthesize_ledger

        entry = synthesize_ledger(git_diff=git_diff, notes=notes, state=state).strip()
    except Exception as e:
        # Facts-only fallback so the canonical ledger still records the day.
        entry = (
            f"# Ledger: {_today_utc()}\n\n"
            "## Summary\n"
            "Ledger synthesis unavailable; entry recorded without synthesis.\n\n"
            "## Events\n"
            "- Time (if known): Ledger synthesis attempted but unavailable.\n\n"
            "## Artifacts\n"
            "- git diff --stat:\n"
            f"{git_diff.strip()}\n"
            "- notes:\n"
            f"{notes.strip()}\n"
            "- state:\n"
            f"{state.strip()}\n\n"
            "## Metrics\n"
            "- Tokens: (unknown)\n"
            f"- Errors: {type(e).__name__}: {e}\n"
        )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            payload = "\n\n" + entry + "\n"
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        return False

    return True
