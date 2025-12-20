from __future__ import annotations

import subprocess
from typing import Optional

from synthdesk.ops.ledger import append_synthesized_ledger


def _git_diff_stat() -> str:
    """
    Lightweight summary of repo changes for the ledger.
    """

    return subprocess.getoutput("git diff --stat")


def run_ledger(notes: str, state: str) -> bool:
    """
    Human-gated end-of-day ledger synthesis.

    - Must be called explicitly.
    - At most once per day by convention.
    """

    git_diff = _git_diff_stat()
    return append_synthesized_ledger(
        git_diff=git_diff,
        notes=notes,
        state=state,
    )

