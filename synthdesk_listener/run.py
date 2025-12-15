from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


LISTENER_VERSION = "v0.x"
COINBASE_EXCHANGE = "coinbase"
COINBASE_CANDLES_URL_TEMPLATE = "https://api.exchange.coinbase.com/products/{product_id}/candles"


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    seconds: int

    @property
    def start_str(self) -> str:
        return _format_utc(self.start)

    @property
    def end_str(self) -> str:
        return _format_utc(self.end)


def _format_utc(dt: datetime) -> str:
    utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_symbols(raw: str) -> list[str]:
    symbols = [part.strip() for part in raw.split(",")]
    canonical = [s.upper() for s in symbols if s]
    if not canonical:
        raise ValueError("symbols must be a non-empty comma-separated list")
    return canonical


def _parse_resolution_seconds(raw: str) -> tuple[str, int]:
    if not raw.endswith("s"):
        raise ValueError("resolution must end with 's' (e.g. 60s)")
    digits = raw[:-1]
    if not digits.isdigit():
        raise ValueError("resolution must be of form <seconds>s (e.g. 60s)")
    seconds = int(digits)
    if seconds <= 0:
        raise ValueError("resolution seconds must be > 0")
    if seconds % 60 != 0:
        raise ValueError("resolution seconds must be a multiple of 60")
    normalized = f"{seconds}s"
    return normalized, seconds


def _last_fully_closed_interval(resolution_seconds: int, now: datetime) -> Interval:
    now_utc = now.astimezone(timezone.utc).replace(microsecond=0)
    now_epoch = int(now_utc.timestamp())
    start_epoch = ((now_epoch // resolution_seconds) - 1) * resolution_seconds
    start = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
    end = start + timedelta(seconds=resolution_seconds - 1)
    if int(start.timestamp()) % resolution_seconds != 0:
        raise ValueError("computed interval_start is not aligned to resolution")
    return Interval(start=start, end=end, seconds=resolution_seconds)


def _jsonl_has_interval(path: Path, symbol: str, resolution: str, interval_start: str) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid_jsonl_line: {exc.msg}") from exc
                if not isinstance(obj, dict):
                    raise ValueError("invalid_jsonl_line: expected object")
                if (
                    obj.get("symbol") == symbol
                    and obj.get("resolution") == resolution
                    and obj.get("interval_start") == interval_start
                ):
                    return True
    except OSError as exc:
        raise ValueError(f"jsonl_read_error: {exc.strerror}") from exc
    return False


def _fetch_coinbase_candle(
    symbol: str,
    resolution_seconds: int,
    interval_start: datetime,
    interval_end: datetime,
) -> list[Any]:
    query = urllib.parse.urlencode(
        {
            "granularity": str(resolution_seconds),
            "start": _format_utc(interval_start),
            "end": _format_utc(interval_end),
        }
    )
    url = COINBASE_CANDLES_URL_TEMPLATE.format(product_id=urllib.parse.quote(symbol)) + "?" + query
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "synthdesk-listener"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"http_status={exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("network_error") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_schema: invalid_json") from exc
    if not isinstance(payload, list):
        raise ValueError("invalid_schema: expected list")
    return payload


def _validate_single_candle(
    payload: list[Any],
    expected_start_epoch: int,
) -> tuple[float, float, float, float, float]:
    if len(payload) != 1:
        raise ValueError("invalid_schema: expected exactly one candle")
    candle = payload[0]
    if not isinstance(candle, list) or len(candle) != 6:
        raise ValueError("invalid_schema: candle must be [time,low,high,open,close,volume]")
    raw_time, raw_low, raw_high, raw_open, raw_close, raw_volume = candle
    if not isinstance(raw_time, int):
        raise ValueError("invalid_schema: candle time must be int epoch seconds")
    if raw_time != expected_start_epoch:
        raise ValueError("invalid_timestamps: candle time != interval_start")
    try:
        low = float(raw_low)
        high = float(raw_high)
        open_ = float(raw_open)
        close = float(raw_close)
        volume = float(raw_volume)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_schema: OHLCV values must be numbers") from exc
    for value in (low, high, open_, close, volume):
        if not (value == value and abs(value) != float("inf")):
            raise ValueError("invalid_schema: OHLCV values must be finite")
    return open_, high, low, close, volume


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _error_stderr(message: str) -> None:
    print(message, file=sys.stderr)


def cli(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthdesk_listener.run")
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols (e.g. BTC-USD,ETH-USD)")
    parser.add_argument("--resolution", required=True, help="Resolution in seconds (e.g. 60s)")
    parser.add_argument("--output-dir", required=True, help="Output directory path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        symbols = _parse_symbols(args.symbols)
        resolution, resolution_seconds = _parse_resolution_seconds(args.resolution)
        output_dir = Path(args.output_dir)
    except ValueError as exc:
        _error_stderr(f"error=invalid_args detail={str(exc).replace(' ', '_')}")
        return 2

    interval = _last_fully_closed_interval(resolution_seconds, datetime.now(timezone.utc))
    interval_start_str = interval.start_str

    wrote_any = False
    skipped: list[str] = []

    for symbol in symbols:
        out_path = output_dir / interval.start.strftime("%Y-%m-%d") / f"listener_{symbol.lower()}.jsonl"
        try:
            if _jsonl_has_interval(out_path, symbol, resolution, interval_start_str):
                skipped.append(symbol)
                continue
        except ValueError as exc:
            _error_stderr(f"error=validation_failure symbol={symbol} detail={str(exc).replace(' ', '_')}")
            return 2

        try:
            payload = _fetch_coinbase_candle(symbol, resolution_seconds, interval.start, interval.end)
        except RuntimeError as exc:
            _error_stderr(f"error=network_failure symbol={symbol} detail={str(exc)}")
            return 1
        except ValueError as exc:
            _error_stderr(f"error=validation_failure symbol={symbol} detail={str(exc).replace(' ', '_')}")
            return 2

        try:
            open_, high, low, close, volume = _validate_single_candle(payload, int(interval.start.timestamp()))
        except ValueError as exc:
            _error_stderr(f"error=validation_failure symbol={symbol} detail={str(exc).replace(' ', '_')}")
            return 2

        record = {
            "symbol": symbol,
            "exchange": COINBASE_EXCHANGE,
            "resolution": resolution,
            "interval_start": interval.start_str,
            "interval_end": interval.end_str,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "collected_at": _format_utc(datetime.now(timezone.utc)),
            "listener_version": LISTENER_VERSION,
        }
        _append_jsonl(out_path, record)
        wrote_any = True

    if not wrote_any:
        print(f"noop interval_start={interval_start_str} resolution={resolution} symbols={','.join(skipped)}")
    return 0


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
