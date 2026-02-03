from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import websockets


BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"


async def connect_stream(stream: str) -> AsyncIterator[dict[str, Any]]:
    """
    Connects to a single binance stream via /ws/<stream> and yields decoded json messages.

    Reconnect policy:
    - infinite loop
    - exponential backoff capped
    """
    url = f"{BINANCE_WS_BASE}/{stream}"
    backoff = 0.5
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:
                backoff = 0.5
                async for msg in ws:
                    if not msg:
                        continue
                    yield json.loads(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 10.0)
