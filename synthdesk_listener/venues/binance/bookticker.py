from __future__ import annotations

from synthdesk_listener.contract.v1.envelope import build_book_ticker_envelope
from synthdesk_listener.emit.jsonl_rotator import JsonlDailyRotator
from synthdesk_listener.util.time import now_ns
from synthdesk_listener.venues.binance.ws import connect_stream


def _stream_name(symbol: str) -> str:
    return f"{symbol.lower()}@bookTicker"


async def run_bookticker(
    *,
    symbol: str,
    raw_root: str,
    listener_id: str,
    include_raw: bool,
    logger,
) -> None:
    rot = JsonlDailyRotator(raw_root=raw_root, venue="binance", symbol=symbol, channel="bookTicker")
    stream = _stream_name(symbol)
    logger.info(f"binance bookticker connect stream={stream} symbol={symbol} raw_root={raw_root}")
    try:
        async for msg in connect_stream(stream):
            ts_recv = now_ns()
            data = msg.get("data") if isinstance(msg, dict) else None
            if not isinstance(data, dict) and isinstance(msg, dict):
                data = msg
            if not isinstance(data, dict):
                continue
            if data.get("e") != "bookTicker":
                continue
            env = build_book_ticker_envelope(
                venue="binance",
                symbol=symbol,
                ts_recv_ns=ts_recv,
                listener_id=listener_id,
                data=data,
                include_raw=include_raw,
            )
            rot.write(env)
    finally:
        rot.close()

