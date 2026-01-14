"""
Listener configuration management.

Provides typed configuration with symbol validation against the spine SDK registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Try to import from spine_sdk, fallback to inline defaults
try:
    from synthdesk_spine.symbols import (
        DEFAULT_SYMBOLS,
        SUPPORTED_SYMBOLS,
        validate_symbols,
    )
except ImportError:
    # Inline fallback for standalone listener operation
    SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
    DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT"]

    def validate_symbols(symbols: List[str]) -> List[str]:
        valid = [s for s in symbols if s in SUPPORTED_SYMBOLS]
        if not valid:
            raise ValueError(f"No valid symbols: {symbols}")
        return valid


@dataclass
class ListenerConfig:
    """
    Typed listener configuration.

    All symbols are validated against the canonical SymbolRegistry.
    """

    pairs: List[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    poll_interval_seconds: int = 10
    vol_window: int = 60
    log_level: str = "INFO"
    log_file: Optional[str] = None
    regime_debug: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Validate symbols against registry
        self.pairs = validate_symbols(self.pairs)

        # Validate poll interval
        if self.poll_interval_seconds < 1:
            raise ValueError(f"poll_interval_seconds must be >= 1, got {self.poll_interval_seconds}")

        # Validate vol_window
        if self.vol_window < 2:
            raise ValueError(f"vol_window must be >= 2, got {self.vol_window}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ListenerConfig":
        """Create config from dictionary with defaults."""
        return cls(
            pairs=data.get("pairs", list(DEFAULT_SYMBOLS)),
            poll_interval_seconds=data.get("poll_interval_seconds", 10),
            vol_window=data.get("vol_window", 60),
            log_level=data.get("log_level", "INFO"),
            log_file=data.get("log_file"),
            regime_debug=data.get("regime_debug", False),
        )

    @classmethod
    def from_json(cls, path: Path) -> "ListenerConfig":
        """Load config from JSON file."""
        with path.open() as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "pairs": self.pairs,
            "poll_interval_seconds": self.poll_interval_seconds,
            "vol_window": self.vol_window,
            "log_level": self.log_level,
            "log_file": self.log_file,
            "regime_debug": self.regime_debug,
        }


# Example configs for different deployment scenarios
SINGLE_SYMBOL_CONFIG = ListenerConfig(pairs=["BTCUSDT"])
DUAL_SYMBOL_CONFIG = ListenerConfig(pairs=["BTCUSDT", "ETHUSDT"])
MULTI_SYMBOL_CONFIG = ListenerConfig(pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
