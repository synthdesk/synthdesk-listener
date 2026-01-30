"""
Semantic startup classification.

Derives startup_type (cold | resume | recover) from existing artifacts.
Pure function — no side effects, no systemd calls, no notifications.

startup_type is a deterministic function of startup_evidence, not an
independent claim. Future auditors can recompute the classification
from the evidence dict alone.

See: DOCTRINE_STARTUP_SEMANTICS_V0.md
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Literal, Dict, Any, Tuple
import json


StartupType = Literal["cold", "resume", "recover"]


@dataclass(frozen=True)
class StartupEvidence:
    """Raw artifact facts. No interpretation — classification is computed separately."""

    state_path: str
    state_exists: bool
    state_corrupt: bool
    state_offsets_nonzero: bool
    state_updated_at_present: bool

    lifecycle_path: Optional[str]
    lifecycle_exists: Optional[bool]
    lifecycle_last_start_unterminated: Optional[bool]
    lifecycle_has_any_start: Optional[bool]

    checkpoint_path: Optional[str]
    checkpoint_exists: Optional[bool]
    checkpoint_corrupt: Optional[bool]

    ledger_path: Optional[str]
    ledger_exists: Optional[bool]
    ledger_nonempty: Optional[bool]


def _safe_read_json(path: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Returns (ok, obj).
    ok=False means file exists but unreadable/corrupt.
    ok=True with obj=None means missing.
    """
    if not path.exists():
        return True, None
    try:
        return True, json.loads(path.read_text())
    except Exception:
        return False, None


def _ledger_facts(path: Optional[Path]) -> Tuple[Optional[bool], Optional[bool]]:
    if path is None:
        return None, None
    if not path.exists():
        return False, False
    try:
        size = path.stat().st_size
        return True, size > 0
    except Exception:
        return True, None


def _state_facts(state_path: Path) -> Tuple[bool, bool, bool, bool]:
    """Returns: (exists, corrupt, offsets_nonzero, updated_at_present)."""
    ok, obj = _safe_read_json(state_path)
    if obj is None and ok:
        return False, False, False, False  # missing
    if not ok:
        return True, True, False, False  # exists but corrupt

    updated_at_present = bool(obj.get("updated_at")) if isinstance(obj, dict) else False

    offsets = []
    if isinstance(obj, dict):
        for k in ("geometry_offset", "episodes_offset", "offset", "cursor", "byte_offset"):
            v = obj.get(k)
            if isinstance(v, int):
                offsets.append(v)

    offsets_nonzero = any(v > 0 for v in offsets) if offsets else False
    return True, False, offsets_nonzero, updated_at_present


def _lifecycle_facts(
    lifecycle_path: Optional[Path],
) -> Tuple[Optional[bool], Optional[bool], Optional[bool]]:
    """
    Returns: (exists, has_any_start, last_start_unterminated).
    Conservative: invalid JSON lines are skipped, not treated as crash evidence.
    """
    if lifecycle_path is None:
        return None, None, None
    if not lifecycle_path.exists():
        return False, False, False

    has_start = False
    started = 0
    terminated = 0

    try:
        for raw in lifecycle_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            et = rec.get("event") or rec.get("event_type") or rec.get("type")
            if et == "RUNNER_START":
                has_start = True
                started += 1
            elif et in ("RUNNER_TERMINATED", "RUNNER_STOP", "RUNNER_EXIT"):
                terminated += 1

        if has_start:
            return True, True, started > terminated
        return True, False, False
    except Exception:
        return True, None, None


def _checkpoint_facts(
    checkpoint_path: Optional[Path],
) -> Tuple[Optional[bool], Optional[bool]]:
    """Returns: (exists, corrupt)."""
    if checkpoint_path is None:
        return None, None
    if not checkpoint_path.exists():
        return False, False
    try:
        txt = checkpoint_path.read_text().strip()
        if not txt:
            return True, False
        if txt.startswith("{"):
            json.loads(txt)  # raises on corrupt JSON
        return True, False
    except (json.JSONDecodeError, ValueError):
        return True, True
    except Exception:
        return True, False  # read error, not necessarily corrupt


def classify_startup(
    *,
    state_path: str,
    lifecycle_path: Optional[str] = None,
    checkpoint_path: Optional[str] = None,
    ledger_path: Optional[str] = None,
) -> Tuple[StartupType, Dict[str, Any]]:
    """
    Deterministic decision tree:
      1. recover — if strong crash indicators (state corrupt, dirty lifecycle, checkpoint corrupt)
      2. cold    — if no prior state signals anywhere
      3. resume  — otherwise
    """
    sp = Path(state_path)
    lp = Path(lifecycle_path) if lifecycle_path else None
    cp = Path(checkpoint_path) if checkpoint_path else None
    led = Path(ledger_path) if ledger_path else None

    state_exists, state_corrupt, state_offsets_nonzero, state_updated_at_present = _state_facts(sp)
    lifecycle_exists, lifecycle_has_start, lifecycle_dirty = _lifecycle_facts(lp)
    checkpoint_exists, checkpoint_corrupt = _checkpoint_facts(cp)
    ledger_exists, ledger_nonempty = _ledger_facts(led)

    ev = StartupEvidence(
        state_path=str(sp),
        state_exists=state_exists,
        state_corrupt=state_corrupt,
        state_offsets_nonzero=state_offsets_nonzero,
        state_updated_at_present=state_updated_at_present,
        lifecycle_path=str(lp) if lp else None,
        lifecycle_exists=lifecycle_exists,
        lifecycle_last_start_unterminated=lifecycle_dirty,
        lifecycle_has_any_start=lifecycle_has_start,
        checkpoint_path=str(cp) if cp else None,
        checkpoint_exists=checkpoint_exists,
        checkpoint_corrupt=checkpoint_corrupt,
        ledger_path=str(led) if led else None,
        ledger_exists=ledger_exists,
        ledger_nonempty=ledger_nonempty,
    )

    evidence_dict = asdict(ev)

    # ---- verdict logic (recomputable from evidence) ----

    # Strong crash indicators => recover
    if ev.state_corrupt:
        return "recover", {"evidence": evidence_dict, "rule": "state_corrupt"}
    if ev.lifecycle_last_start_unterminated is True:
        return "recover", {"evidence": evidence_dict, "rule": "dirty_lifecycle"}
    if ev.checkpoint_corrupt is True:
        return "recover", {"evidence": evidence_dict, "rule": "checkpoint_corrupt"}

    # No trace of prior run => cold
    prior_signals = []
    if ev.state_exists:
        prior_signals.append("state_exists")
    if ev.lifecycle_has_any_start:
        prior_signals.append("lifecycle_has_start")
    if ev.checkpoint_exists:
        prior_signals.append("checkpoint_exists")
    if ev.ledger_nonempty:
        prior_signals.append("ledger_nonempty")
    if ev.state_offsets_nonzero or ev.state_updated_at_present:
        prior_signals.append("state_has_progress")

    if len(prior_signals) == 0:
        return "cold", {"evidence": evidence_dict, "rule": "no_prior_state"}

    # Otherwise resume
    return "resume", {"evidence": evidence_dict, "rule": "default_resume"}
