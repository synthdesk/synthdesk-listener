"""
Human-invoked invariant review artifact writer.

Intent: generate an explanatory Markdown artifact for a violated expectation,
without mutating any system state beyond writing the artifact file.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


def _synthdesk_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _invariants_dir() -> Path:
    return _synthdesk_dir() / "invariants"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_slug(value: str) -> str:
    """
    Conservative filename slug to avoid path traversal or odd characters.
    """

    value = str(value).strip()
    if not value:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    slug = slug.strip("._-") or "unknown"
    return slug[:80]


def write_invariant_review(
    expectation_id: str,
    expectation_text: str,
    violation_context: str,
) -> bool:
    """
    Create a fixed-schema Markdown artifact for a violated expectation.

    - Human-invoked only: this function does not schedule itself.
    - Never overwrites existing files.
    - Swallows AI/IO failures safely.
    """

    markdown = None
    ai_error = None
    try:
        from synthdesk.ai.wrapper import explain_invariant

        markdown = explain_invariant(
            expectation_id=expectation_id,
            expectation_text=expectation_text,
            violation_context=violation_context,
        ).strip()
    except Exception as e:
        ai_error = f"{type(e).__name__}: {e}"

    if markdown is None:
        # Facts-only fallback: preserve the fixed schema even when AI is unavailable.
        date_str = _today_utc()
        markdown = (
            f"# Invariant Review: {expectation_id}\n"
            f"Date: {date_str}\n\n"
            "## Expectation\n"
            f"{expectation_text}\n\n"
            "## Observed Violation\n"
            f"{violation_context}\n\n"
            "## Possible Explanations\n"
            "Invariant synthesis unavailable; no additional explanations recorded.\n\n"
            "## What This Does NOT Imply\n"
            "No implications recorded.\n\n"
            "## Questions for Human Review\n"
            f"- AI unavailable: {ai_error or 'unknown error'}\n\n"
            "## Human Decision\n"
        ).strip()

    out_dir = _invariants_dir()
    slug = _safe_slug(expectation_id)
    date_str = _today_utc()
    path = out_dir / f"invariant_review_{slug}_{date_str}.md"

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(markdown)
            if not markdown.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        return False

    return True
