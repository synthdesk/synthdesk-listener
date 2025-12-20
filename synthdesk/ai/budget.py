"""
Token/cost budgeting utilities.

Intent:
- Track per-run usage (tokens, cost, latency).
- Enforce configurable budgets and report overruns.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_MONTHLY_LIMIT_TOKENS = 2_000_000
DEFAULT_RESET_SECONDS = 30 * 24 * 60 * 60


class BudgetError(RuntimeError):
    """
    Base error for budget fuse failures.

    Callers should catch this (or subclasses) and treat it as "AI going dark"
    rather than crashing the whole process.
    """


class BudgetExceeded(BudgetError):
    """
    Raised when a token allocation would exceed the monthly limit.
    """


class BudgetStorageError(BudgetError):
    """
    Raised when the budget state cannot be read/written safely.
    """


@dataclass(frozen=True)
class _BudgetState:
    period_start_ts: float
    tokens_used: int

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "period_start_ts": self.period_start_ts,
            "tokens_used": self.tokens_used,
        }

    @staticmethod
    def from_json(payload: Dict[str, Any]) -> "_BudgetState":
        try:
            schema_version = int(payload.get("schema_version", 1))
            if schema_version != 1:
                raise ValueError(f"Unsupported schema_version={schema_version}")
            period_start_ts = float(payload["period_start_ts"])
            tokens_used = int(payload["tokens_used"])
        except Exception as exc:  # noqa: BLE001 - normalize to BudgetStorageError
            raise ValueError("Invalid budget state JSON") from exc
        if tokens_used < 0:
            raise ValueError("Invalid budget state: tokens_used < 0")
        return _BudgetState(period_start_ts=period_start_ts, tokens_used=tokens_used)


def default_budget_path() -> Path:
    """
    Default location for the local budget fuse state.

    Env override:
    - SYNTHDESK_BUDGET_FILE=/path/to/budget.json
    """

    override = os.environ.get("SYNTHDESK_BUDGET_FILE")
    if override:
        return Path(override).expanduser()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "runs" / "budget.json"


def default_monthly_limit_tokens() -> int:
    """
    Default monthly token cap (hard stop).

    Env override:
    - SYNTHDESK_MONTHLY_TOKEN_LIMIT=2000000
    """

    raw = os.environ.get("SYNTHDESK_MONTHLY_TOKEN_LIMIT")
    if not raw:
        return DEFAULT_MONTHLY_LIMIT_TOKENS
    try:
        value = int(raw)
    except ValueError as exc:  # noqa: BLE001 - normalize to BudgetStorageError
        raise BudgetStorageError("Invalid SYNTHDESK_MONTHLY_TOKEN_LIMIT (must be int)") from exc
    if value <= 0:
        raise BudgetStorageError("Invalid SYNTHDESK_MONTHLY_TOKEN_LIMIT (must be > 0)")
    return value


class MonthlyTokenBudget:
    """
    Local, file-backed monthly token counter.

    - Resets automatically every ~30 days (rolling window from period start).
    - Persists to JSON so restarts don't bypass the fuse.
    - Exceeding the cap raises BudgetExceeded (a RuntimeError).
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        monthly_limit_tokens: Optional[int] = None,
        reset_seconds: int = DEFAULT_RESET_SECONDS,
    ) -> None:
        self._path = path if path is not None else default_budget_path()
        self._monthly_limit_tokens = (
            monthly_limit_tokens if monthly_limit_tokens is not None else default_monthly_limit_tokens()
        )
        self._reset_seconds = int(reset_seconds)

        if self._reset_seconds <= 0:
            raise BudgetStorageError("reset_seconds must be > 0")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def monthly_limit_tokens(self) -> int:
        return self._monthly_limit_tokens

    def reset(self, *, now_ts: Optional[float] = None) -> None:
        """
        Force-reset the budget window and token counter.
        """

        now = float(time.time() if now_ts is None else now_ts)
        self._write_state(_BudgetState(period_start_ts=now, tokens_used=0))

    def get_state(self, *, now_ts: Optional[float] = None) -> _BudgetState:
        """
        Read state (applying automatic reset if the period expired).
        """

        now = float(time.time() if now_ts is None else now_ts)
        state = self._read_state(now_ts=now)
        reset_state = self._maybe_reset(state, now_ts=now)
        if reset_state != state:
            self._write_state(reset_state)
        return reset_state

    def remaining_tokens(self, *, now_ts: Optional[float] = None) -> int:
        state = self.get_state(now_ts=now_ts)
        return max(0, self._monthly_limit_tokens - state.tokens_used)

    def consume(self, tokens: int, *, now_ts: Optional[float] = None) -> int:
        """
        Atomically add `tokens` to the counter.

        Returns the new `tokens_used` total. Raises BudgetExceeded if this would
        exceed the monthly cap.
        """

        if not isinstance(tokens, int):
            raise BudgetStorageError("tokens must be an int")
        if tokens < 0:
            raise BudgetStorageError("tokens must be >= 0")
        if tokens == 0:
            return self.get_state(now_ts=now_ts).tokens_used

        now = float(time.time() if now_ts is None else now_ts)
        state = self._maybe_reset(self._read_state(now_ts=now), now_ts=now)
        new_total = state.tokens_used + tokens

        if new_total > self._monthly_limit_tokens:
            raise BudgetExceeded(
                f"Monthly token budget exceeded: used={state.tokens_used}, "
                f"adding={tokens}, limit={self._monthly_limit_tokens}"
            )

        new_state = _BudgetState(period_start_ts=state.period_start_ts, tokens_used=new_total)
        self._write_state(new_state)
        return new_total

    def _maybe_reset(self, state: _BudgetState, *, now_ts: float) -> _BudgetState:
        if (now_ts - state.period_start_ts) >= self._reset_seconds:
            return _BudgetState(period_start_ts=now_ts, tokens_used=0)
        return state

    def _read_state(self, *, now_ts: float) -> _BudgetState:
        path = self._path
        try:
            if not path.exists():
                # First run: start a fresh budget window at first use.
                return _BudgetState(period_start_ts=now_ts, tokens_used=0)
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return _BudgetState.from_json(payload)
        except BudgetStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to BudgetStorageError
            raise BudgetStorageError(f"Failed to read budget state: {path}") from exc

    def _write_state(self, state: _BudgetState) -> None:
        path = self._path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(state.to_json(), handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001 - normalize to BudgetStorageError
            raise BudgetStorageError(f"Failed to write budget state: {path}") from exc


_DEFAULT_BUDGET: Optional[MonthlyTokenBudget] = None


def get_default_budget() -> MonthlyTokenBudget:
    """
    Lazily-constructed process-global budget instance.
    """

    global _DEFAULT_BUDGET
    if _DEFAULT_BUDGET is None:
        _DEFAULT_BUDGET = MonthlyTokenBudget()
    return _DEFAULT_BUDGET


def consume_tokens(tokens: int, *, now_ts: Optional[float] = None) -> int:
    """
    Convenience wrapper for the default local budget fuse.
    """

    return get_default_budget().consume(tokens, now_ts=now_ts)


def check_and_consume(estimated_tokens: int, *, now_ts: Optional[float] = None) -> int:
    """
    Pre-consume an estimated token cost before making an AI call.

    Intent: budget enforcement happens *before* external calls so "AI going dark"
    is a controlled RuntimeError instead of uncontrolled spend.
    """

    return consume_tokens(estimated_tokens, now_ts=now_ts)
