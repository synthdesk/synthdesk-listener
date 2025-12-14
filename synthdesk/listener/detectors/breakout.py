"""
breakout detector (stub interface).

real implementation will plug into price_listener metrics:
- rolling_mean
- rolling_std
- breakout thresholds

todo:
- unify signature with vol_spike + mr_touch detectors
- move hardcoded thresholds into config
"""


def detect_breakout(pair, price, rolling_mean, threshold, ts):
    return None

