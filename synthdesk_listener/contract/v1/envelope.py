from __future__ import annotations

from typing import Any

from synthdesk_listener.util.time import ms_to_ns


def _base(
    *,
    event_type: str,
    venue: str,
    symbol: str,
    channel: str,
    event_id: int,
    seq: int,
    ts_event_ms: int,
    ts_recv_ns: int,
    listener_id: str,
    schema_id: str,
    payload: dict[str, Any],
    payload_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env: dict[str, Any] = {
        "event_version": 1,
        "event_type": event_type,
        "venue": venue,
        "symbol": symbol,
        "channel": channel,
        "event_id": int(event_id),
        "seq": int(seq),
        "ts_event_ns": ms_to_ns(int(ts_event_ms)),
        "ts_recv_ns": int(ts_recv_ns),
        "source": {"listener_id": listener_id, "schema_id": schema_id},
        "payload": payload,
    }
    if payload_raw is not None:
        env["payload_raw"] = payload_raw
    return env


def build_agg_trade_envelope(
    *,
    venue: str,
    symbol: str,
    ts_recv_ns: int,
    listener_id: str,
    data: dict[str, Any],
    include_raw: bool = False,
) -> dict[str, Any]:
    trade_id = int(data["a"])
    ts_event_ms = int(data["T"])
    payload = {
        "trade_id": trade_id,
        "price": data["p"],
        "qty": data["q"],
        "first_trade_id": int(data["f"]),
        "last_trade_id": int(data["l"]),
        "buyer_maker": bool(data["m"]),
        "is_best_match": bool(data["M"]),
        "ts_event_ms": ts_event_ms,
    }
    return _base(
        event_type="agg_trade",
        venue=venue,
        symbol=symbol,
        channel="aggTrade",
        event_id=trade_id,
        seq=trade_id,
        ts_event_ms=ts_event_ms,
        ts_recv_ns=ts_recv_ns,
        listener_id=listener_id,
        schema_id="binance.agg_trade.v1",
        payload=payload,
        payload_raw={"binance": {"data": data}} if include_raw else None,
    )


def build_depth_update_envelope(
    *,
    venue: str,
    symbol: str,
    ts_recv_ns: int,
    listener_id: str,
    data: dict[str, Any],
    include_raw: bool = False,
) -> dict[str, Any]:
    first_update_id = int(data["U"])
    last_update_id = int(data["u"])
    ts_event_ms = int(data["E"])
    payload = {
        "first_update_id": first_update_id,
        "last_update_id": last_update_id,
        "bids": data["b"],
        "asks": data["a"],
        "ts_event_ms": ts_event_ms,
    }
    return _base(
        event_type="depth_update",
        venue=venue,
        symbol=symbol,
        channel="depth",
        event_id=last_update_id,
        seq=last_update_id,
        ts_event_ms=ts_event_ms,
        ts_recv_ns=ts_recv_ns,
        listener_id=listener_id,
        schema_id="binance.depth.v1",
        payload=payload,
        payload_raw={"binance": {"data": data}} if include_raw else None,
    )


def build_book_ticker_envelope(
    *,
    venue: str,
    symbol: str,
    ts_recv_ns: int,
    listener_id: str,
    data: dict[str, Any],
    include_raw: bool = False,
) -> dict[str, Any]:
    update_id = int(data["u"])
    ts_event_ms = int(data.get("E", ts_recv_ns // 1_000_000))
    payload = {
        "update_id": update_id,
        "bid_price": data["b"],
        "bid_qty": data["B"],
        "ask_price": data["a"],
        "ask_qty": data["A"],
        "ts_event_ms": ts_event_ms,
    }
    return _base(
        event_type="book_ticker",
        venue=venue,
        symbol=symbol,
        channel="bookTicker",
        event_id=update_id,
        seq=update_id,
        ts_event_ms=ts_event_ms,
        ts_recv_ns=ts_recv_ns,
        listener_id=listener_id,
        schema_id="binance.book_ticker.v1",
        payload=payload,
        payload_raw={"binance": {"data": data}} if include_raw else None,
    )
