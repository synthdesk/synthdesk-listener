"""
detector modules: breakout, vol spike, mr touch.
"""

from .breakout import detect_breakout
from .mr_touch import detect_mr_touch
from .vol_spike import detect_vol_spike

__all__ = ["detect_breakout", "detect_vol_spike", "detect_mr_touch"]

