from __future__ import annotations

from typing import Any

from synthdesk_listener.contract.v1.envelope import build_agg_trade_envelope
from synthdesk_listener.emit.jsonl_rotator import JsonlDailyRotator
from synthdesk_listener.util.time import now_ns
from synthdesk_listener.venues.binance.ws import connect_stream


def _stream_name(symbol: str) -> str:
    return f"{symbol.lower()}@aggTrade"


async def run_aggtrade(
    *,
    symbol: str,
    raw_root: str,
    listener_id: str,
    include_raw: bool,
    logger,
) -> None:
    rot = JsonlDailyRotator(raw_root=raw_root, venue="binance", symbol=symbol, channel="aggTrade")
    stream = _stream_name(symbol)
    logger.info(f"binance aggtrade connect stream={stream} symbol={symbol} raw_root={raw_root}")
    try:
        async for msg in connect_stream(stream):
            ts_recv = now_ns()
            data = msg.get("data") if isinstance(msg, dict) else None
            if not isinstance(data, dict):
                continue
            if data.get("e") != "aggTrade":
                continue
            env = build_agg_trade_envelope(
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
