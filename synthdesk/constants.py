from datetime import datetime, timezone

REGIME_EPOCH_START = "2025-12-30T07:09:28.445034+00:00"
REGIME_EPOCH_START_DT = datetime.fromisoformat(REGIME_EPOCH_START).astimezone(timezone.utc)
