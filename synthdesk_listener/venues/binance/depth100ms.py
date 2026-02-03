from __future__ import annotations

from synthdesk_listener.contract.v1.envelope import build_depth_update_envelope
from synthdesk_listener.emit.jsonl_rotator import JsonlDailyRotator
from synthdesk_listener.util.time import now_ns
from synthdesk_listener.venues.binance.ws import connect_stream


def _stream_name(symbol: str, interval: str) -> str:
    if interval != "100ms":
        raise ValueError("only 100ms supported in this v1 sensor")
    return f"{symbol.lower()}@depth@100ms"


async def run_depth(
    *,
    symbol: str,
    interval: str,
    raw_root: str,
    listener_id: str,
    include_raw: bool,
    logger,
) -> None:
    rot = JsonlDailyRotator(raw_root=raw_root, venue="binance", symbol=symbol, channel="depth")
    stream = _stream_name(symbol, interval)
    logger.info(f"binance depth connect stream={stream} symbol={symbol} raw_root={raw_root}")
    try:
        async for msg in connect_stream(stream):
            ts_recv = now_ns()
            data = msg.get("data") if isinstance(msg, dict) else None
            if not isinstance(data, dict):
                continue
            if data.get("e") != "depthUpdate":
                continue
            env = build_depth_update_envelope(
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
