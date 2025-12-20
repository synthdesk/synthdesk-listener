"""
Model/provider wrapper surface area.

Intent:
- Centralize model invocation and response normalization.
- Provide hooks for tracing, retries, and structured outputs.
"""

# AI AIRLOCK (SCOPE GUARD)
# - This module is the Synthdesk AI airlock: the only place OpenAI is called.
# - No trading logic may ever import this module (directly or indirectly).
# - No execution authority is permitted: outputs are suggestions/text only.
# - Expanding capabilities requires explicit review and approval.

from __future__ import annotations

import os
from datetime import datetime, timezone

from synthdesk.ai.budget import check_and_consume
from synthdesk.ai.prompts import (
    ARCHITECTURE_DRIFT_PROMPT,
    INVARIANT_EXPLANATION_PROMPT,
    LEDGER_PROMPT,
    REGIME_SUMMARY_PROMPT,
    REPAIR_PROMPT,
)

__all__ = [
    "suggest_patch",
    "synthesize_ledger",
    "explain_invariant",
    "summarize_regime",
    "summarize_architecture_drift",
]

# Single cheap + reliable default model for all calls.
_MODEL = "gpt-4o-mini"


def _estimate_tokens(text: str) -> int:
    """
    Very rough token estimator (no external deps).

    Intent: enforce the hard cap before making network calls.
    """

    # Typical English text is ~4 chars/token; add overhead for chat framing.
    return max(1, (len(text) // 4) + 200)


def _call_openai(*, prompt: str, max_output_tokens: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY")

    estimated_total = _estimate_tokens(prompt) + int(max_output_tokens)
    check_and_consume(estimated_total)

    try:
        from openai import OpenAI  # keep OpenAI usage confined to this module
    except Exception as exc:  # noqa: BLE001 - normalize to RuntimeError
        raise RuntimeError("OpenAI client not available") from exc

    client = OpenAI(api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=int(max_output_tokens),
        )
    except Exception as exc:  # noqa: BLE001 - normalize to RuntimeError
        raise RuntimeError("OpenAI call failed") from exc

    try:
        content = resp.choices[0].message.content
    except Exception as exc:  # noqa: BLE001 - normalize to RuntimeError
        raise RuntimeError("OpenAI returned an unexpected response shape") from exc
    if content is None:
        raise RuntimeError("OpenAI returned empty content")
    return str(content).strip()


def suggest_patch(traceback_text: str) -> str:
    """
    Suggest fixes for a provided traceback (plain text only).
    """

    prompt = (
        REPAIR_PROMPT.replace("<<TRACEBACK>>", traceback_text)
        .replace("<<CONTEXT>>", "")
        .strip()
    )
    return _call_openai(prompt=prompt, max_output_tokens=800)


def synthesize_ledger(git_diff: str, notes: str, state: str) -> str:
    """
    Produce a factual daily ledger entry (Markdown only).
    """

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source = f"GIT DIFF:\n{git_diff}\n\nNOTES:\n{notes}\n\nSTATE:\n{state}".strip()
    prompt = (
        LEDGER_PROMPT.replace("<<DATE>>", date_str)
        .replace("<<SOURCE>>", source)
        .strip()
    )
    return _call_openai(prompt=prompt, max_output_tokens=900)


def explain_invariant(
    expectation_id: str,
    expectation_text: str,
    violation_context: str,
) -> str:
    """
    Explain a violated invariant (Markdown only).
    """

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        INVARIANT_EXPLANATION_PROMPT.replace("<<EXPECTATION_ID>>", expectation_id)
        .replace("<<EXPECTATION_TEXT>>", expectation_text)
        .replace("<<VIOLATION_CONTEXT>>", violation_context)
        .replace("<<DATE>>", date_str)
        .strip()
    )
    return _call_openai(prompt=prompt, max_output_tokens=900)


def summarize_regime(
    date: str,
    window: str,
    aggregates: str,
    prior_period_notes: str,
) -> str:
    """
    Produce a descriptive regime summary (Markdown only).
    """

    prompt = (
        REGIME_SUMMARY_PROMPT.replace("<<DATE>>", date)
        .replace("<<WINDOW>>", window)
        .replace("<<AGGREGATES>>", aggregates)
        .replace("<<PRIOR_PERIOD_NOTES>>", prior_period_notes)
        .strip()
    )
    return _call_openai(prompt=prompt, max_output_tokens=900)


def summarize_architecture_drift(
    window: str,
    ledger_excerpts: str,
    git_diff_summary: str,
    invariant_activity: str,
) -> str:
    """
    Produce a descriptive architecture drift note (Markdown only).
    """

    prompt = (
        ARCHITECTURE_DRIFT_PROMPT.replace("<<WINDOW>>", window)
        .replace("<<LEDGER_EXCERPTS>>", ledger_excerpts)
        .replace("<<GIT_DIFF_SUMMARY>>", git_diff_summary)
        .replace("<<INVARIANT_ACTIVITY>>", invariant_activity)
        .strip()
    )
    return _call_openai(prompt=prompt, max_output_tokens=900)
