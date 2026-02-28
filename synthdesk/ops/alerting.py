"""
Canonical alert sender for synthdesk services.

Consolidates the duplicated alert_sender pattern that was previously:
  1. An external module in synthdesk-listener/scripts/alert_sender.py
  2. Duplicated inline in asymmetry_persistence_v1_runner.py
  3. Duplicated inline in spectral_drift_monitor.py
  4. Wrapped with try/except in 4+ other scripts

Now lives at synthdesk.ops.alerting (packages/listener/synthdesk/ops/alerting.py),
importable by all scripts that add packages/listener to sys.path.

Usage:
    from synthdesk.ops.alerting import send_alert

    send_alert("Engine started", severity="info")
    send_alert("Crash detected", severity="critical")

Incident reference:
    INC-2026-02-27-SOAK-CRASH: bare `from alert_sender import send_alert` crashed
    the soak engine 10,263 times over 8 days because the module wasn't on sys.path.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Severity prefixes for Telegram messages
_SEVERITY_EMOJI = {
    "info": "\u2139\ufe0f",
    "warning": "\u26a0\ufe0f",
    "critical": "\U0001f6a8",
    "recovery": "\u2705",
    "soak": "\U0001f9ea",
}


def send_alert(
    message: str,
    severity: str = "info",
    source: Optional[str] = None,
) -> bool:
    """
    Send alert via Telegram if enabled. Never raises.

    Args:
        message: Alert text (plain text or HTML).
        severity: One of info, warning, critical, recovery, soak.
        source: Optional service identifier (e.g., "soak_v0", "liveness").
                Defaults to SYNTHDESK_ALERT_SOURCE env var or "synthdesk".

    Returns:
        True if Telegram message sent successfully, False otherwise.
        When Telegram is disabled or misconfigured, prints to stdout as fallback.

    Environment variables:
        SYNTHDESK_NOTIFY_TELEGRAM: Set to "1" to enable Telegram delivery.
        TELEGRAM_BOT_TOKEN: Bot API token.
        TELEGRAM_CHAT_ID: Target chat ID.
        SYNTHDESK_ALERT_SOURCE: Default source tag if not passed as argument.
    """
    if source is None:
        source = os.getenv("SYNTHDESK_ALERT_SOURCE", "synthdesk")

    # Always print to stdout for journald capture
    print(f"[{severity.upper()}] [{source}] {message}")

    if os.getenv("SYNTHDESK_NOTIFY_TELEGRAM") != "1":
        return False

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    emoji = _SEVERITY_EMOJI.get(severity, "\U0001f4e2")
    full_message = f"{emoji} <b>[{source}]</b> {message}"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urlencode({
        "chat_id": chat_id,
        "text": full_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        req = Request(url, data=data, method="POST")
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception:
        # Never fail the service because of notification errors.
        # The stdout print above already captured the message for journald.
        return False
