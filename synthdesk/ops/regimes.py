"""
Human-invoked regime summary artifact writer.

Intent: compress aggregated listener observations into a descriptive Markdown
regime summary for archival context. No predictions, no advice, no trades.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _synthdesk_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _regimes_dir() -> Path:
    return _synthdesk_dir() / "regimes"


def _safe_date(value: str) -> str:
    """
    Conservative filename segment for dates (prefer YYYY-MM-DD).
    """

    value = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    value = re.sub(r"[^0-9-]+", "_", value).strip("_")
    return value or "unknown-date"


def _contains_banned_language(markdown: str) -> bool:
    """
    Guardrail: if the model leaks banned terms, fall back to a neutral skeleton.
    """

    lowered = markdown.lower()
    banned = ("bullish", "bearish", "enter", "exit", "expect", "should", "likely")
    return any(term in lowered for term in banned)


def _fallback_markdown(date: str, window: str, aggregates: str, prior_period_notes: str, *, error: str) -> str:
    return (
        f"# Regime Summary: {date}\n\n"
        "## Window\n"
        f"{window}\n\n"
        "## Regime Label\n"
        "Regime synthesis unavailable.\n\n"
        "## Observed Characteristics\n"
        f"{aggregates.strip()}\n\n"
        "## What Changed vs Prior Period\n"
        f"{prior_period_notes.strip() or '(none provided)'}\n\n"
        "## Uncertainties / Blind Spots\n"
        f"- AI unavailable: {error}\n\n"
        "## What This Does NOT Imply\n"
        "- This summary is descriptive context only.\n"
        "- It does not imply direction, signals, or actions.\n"
    ).strip()


def write_regime_summary(
    date: str,
    window: str,
    aggregates: str,
    prior_period_notes: str = "",
) -> bool:
    """
    Create an append-only regime summary artifact (exclusive create).

    Writes: synthdesk/regimes/regime_summary_<YYYY-MM-DD>.md
    """

    safe_date = _safe_date(date)
    out_dir = _regimes_dir()
    path = out_dir / f"regime_summary_{safe_date}.md"

    if path.exists():
        return False

    markdown = None
    ai_error = None
    try:
        from synthdesk.ai.wrapper import summarize_regime

        markdown = summarize_regime(
            date=date,
            window=window,
            aggregates=aggregates,
            prior_period_notes=prior_period_notes,
        ).strip()
    except Exception as e:
        ai_error = f"{type(e).__name__}: {e}"

    if (markdown is None) or _contains_banned_language(markdown):
        markdown = _fallback_markdown(
            date=date,
            window=window,
            aggregates=aggregates,
            prior_period_notes=prior_period_notes,
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

