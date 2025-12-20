import json
import os
import time
from urllib.request import Request, urlopen


def notify_telegram(message: str) -> None:
    if os.getenv("SYNTHDESK_NOTIFY_TELEGRAM") != "1":
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=5):
            return
    except Exception as e:
        # never fail the system because of notifications
        try:
            with open("synthdesk/ops/notify.log", "a", encoding="utf-8") as f:
                f.write(f"{time.time()} telegram notify failed: {e}\n")
        except Exception:
            return
