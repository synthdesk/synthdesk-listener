"""
Non-destructive error repair helper.

Intent: when a worker hits an exception, serialize the full traceback and ask
the AI airlock for a suggested fix, then dump the suggestion to a file for a
human to review. This module never applies changes automatically.
"""

from __future__ import annotations

import os
import socket
import traceback
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_output_path() -> Path:
    return _repo_root() / "auto_patch.txt"


def _atomic_write_text(path: Path, text: str) -> None:
    """
    Best-effort atomic write to avoid partial files under concurrent workers.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def notify_repair(exception_summary: str) -> None:
    try:
        from synthdesk.ops.notify import notify_telegram
    except Exception:
        return

    host = socket.gethostname()
    pid = os.getpid()
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    msg = (
        "[synthdesk] repair suggestion generated\n\n"
        f"time: {ts}\n"
        f"host: {host}\n"
        f"pid: {pid}\n\n"
        f"exception:\n{exception_summary}\n\n"
        "artifact:\n"
        "auto_patch.txt"
    )

    try:
        notify_telegram(msg)
    except Exception:
        return


def dump_repair_suggestion(exc: BaseException, *, output_path: Optional[Path] = None) -> None:
    """
    Serialize `exc` and write an AI-generated repair suggestion to `auto_patch.txt`.

    Safety:
    - Never modifies code or applies patches.
    - AI failures are swallowed (system continues running).
    - File writing is best-effort; any error here is also swallowed.
    """

    path = output_path if output_path is not None else _default_output_path()
    try:
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        tb_text = f"{type(exc).__name__}: {exc}"

    suggestion = None
    ai_error = None
    try:
        from synthdesk.ai.wrapper import suggest_patch

        suggestion = suggest_patch(tb_text)
    except Exception as err:  # noqa: BLE001 - never let AI issues crash workers
        ai_error = f"{type(err).__name__}: {err}"

    exception_summary = f"{type(exc).__name__}: {exc}"
    header = (
        f"auto_patch.txt (non-destructive; review manually)\n"
        f"timestamp_utc: {datetime.now(timezone.utc).isoformat()}\n"
        f"pid: {os.getpid()}\n"
        f"exception: {exception_summary}\n"
    )

    body = "TRACEBACK:\n" + tb_text.strip() + "\n"
    if suggestion is not None:
        body += "\nAI_SUGGESTION (plain text):\n" + suggestion.strip() + "\n"
    else:
        body += "\nAI_UNAVAILABLE:\n" + (ai_error or "unknown error") + "\n"

    payload = header + "\n" + body
    try:
        _atomic_write_text(Path(path), payload)
        if suggestion is not None:
            notify_repair(exception_summary)
        return
    except Exception:
        pass

    # Fallback: if atomic writes are not permitted on this filesystem, attempt a
    # direct overwrite (still non-destructive to the running process).
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            if not payload.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if suggestion is not None:
            notify_repair(exception_summary)
    except Exception:
        return
