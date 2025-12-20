"""
Human-invoked architecture drift note writer (meta-memory).

Intent: summarize how synthdesk's architecture changed over a window using
internal records only. This is descriptive historiography, not planning.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


def _synthdesk_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _architecture_dir() -> Path:
    return _synthdesk_dir() / "architecture"


def _month_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _extract_month(window: str) -> str:
    """
    Best-effort YYYY-MM extraction for naming the artifact file.
    """

    match = re.search(r"\b(\d{4}-\d{2})\b", str(window))
    return match.group(1) if match else _month_utc()


def _contains_banned_language(markdown: str) -> bool:
    """
    Guardrail: force fallback if planning/recommendation language appears.
    """

    lowered = markdown.lower()
    banned = (
        "should",
        "recommend",
        "recommended",
        "recommendation",
        "refactor",
        "roadmap",
        "plan",
        "next step",
    )
    return any(term in lowered for term in banned)


def _fallback_markdown(
    window: str,
    ledger_excerpts: str,
    git_diff_summary: str,
    invariant_activity: str,
    *,
    error: str,
) -> str:
    return (
        f"# Architecture Drift Note: {window}\n\n"
        "## Window\n"
        f"{window}\n\n"
        "## What Changed\n"
        "Architecture drift synthesis unavailable; records captured for reference.\n"
        f"- Ledger excerpts: {ledger_excerpts.strip() or '(none provided)'}\n"
        f"- Git diff summary: {git_diff_summary.strip() or '(none provided)'}\n\n"
        "## Invariants Added / Revised / Retired\n"
        f"{invariant_activity.strip() or '(none provided)'}\n\n"
        "## Complexity Direction\n"
        "(unknown)\n\n"
        "## Emerging Risks\n"
        f"- AI unavailable: {error}\n\n"
        "## What Did NOT Change\n"
        "(unknown)\n\n"
        "## Open Questions for Human Review\n"
        "- (none recorded)\n"
    ).strip()


def write_architecture_drift(
    window: str,
    ledger_excerpts: str,
    git_diff_summary: str,
    invariant_activity: str,
) -> bool:
    """
    Write an exclusive-create drift note artifact for the given window.

    Path: synthdesk/architecture/drift_note_<YYYY-MM>.md
    """

    out_dir = _architecture_dir()
    month = _extract_month(window)
    path = out_dir / f"drift_note_{month}.md"

    if path.exists():
        return False

    markdown = None
    ai_error = None
    try:
        from synthdesk.ai.wrapper import summarize_architecture_drift

        markdown = summarize_architecture_drift(
            window=window,
            ledger_excerpts=ledger_excerpts,
            git_diff_summary=git_diff_summary,
            invariant_activity=invariant_activity,
        ).strip()
    except Exception as e:
        ai_error = f"{type(e).__name__}: {e}"

    if (markdown is None) or _contains_banned_language(markdown):
        markdown = _fallback_markdown(
            window=window,
            ledger_excerpts=ledger_excerpts,
            git_diff_summary=git_diff_summary,
            invariant_activity=invariant_activity,
            error=ai_error or "banned language detected",
        )

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
