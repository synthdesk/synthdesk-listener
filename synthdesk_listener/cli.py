from __future__ import annotations

import argparse
import asyncio
import os

from synthdesk_listener.util.logging import configure_logging
from synthdesk_listener.venues.binance.aggtrade import run_aggtrade
from synthdesk_listener.venues.binance.bookticker import run_bookticker
from synthdesk_listener.venues.binance.depth100ms import run_depth


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthdesk-listener",
        description="sensor-only listeners (wire -> v1 envelope -> disk)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_agg = sub.add_parser("aggtrade", help="binance aggTrade -> v1 envelopes")
    p_agg.add_argument("--symbol", required=True)
    p_agg.add_argument("--raw-root", required=True)
    p_agg.add_argument("--listener-id", required=True)
    p_agg.add_argument("--include-raw", action="store_true", help="include payload_raw.binance")

    p_depth = sub.add_parser("depth", help="binance depthUpdate@100ms -> v1 envelopes")
    p_depth.add_argument("--symbol", required=True)
    p_depth.add_argument("--interval", default="100ms", choices=["100ms"])
    p_depth.add_argument("--raw-root", required=True)
    p_depth.add_argument("--listener-id", required=True)
    p_depth.add_argument("--include-raw", action="store_true", help="include payload_raw.binance")

    p_bt = sub.add_parser("bookticker", help="binance bookTicker -> v1 envelopes")
    p_bt.add_argument("--symbol", required=True)
    p_bt.add_argument("--raw-root", required=True)
    p_bt.add_argument("--listener-id", required=True)
    p_bt.add_argument("--include-raw", action="store_true", help="include payload_raw.binance")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging(level=os.getenv("LOG_LEVEL"))

    if args.cmd == "aggtrade":
        asyncio.run(
            run_aggtrade(
                symbol=args.symbol,
                raw_root=args.raw_root,
                listener_id=args.listener_id,
                include_raw=bool(args.include_raw),
                logger=logger,
            )
        )
        return 0

    if args.cmd == "depth":
        asyncio.run(
            run_depth(
                symbol=args.symbol,
                interval=args.interval,
                raw_root=args.raw_root,
                listener_id=args.listener_id,
                include_raw=bool(args.include_raw),
                logger=logger,
            )
        )
        return 0

    if args.cmd == "bookticker":
        asyncio.run(
            run_bookticker(
                symbol=args.symbol,
                raw_root=args.raw_root,
                listener_id=args.listener_id,
                include_raw=bool(args.include_raw),
                logger=logger,
            )
        )
        return 0

    raise SystemExit("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
