#!/usr/bin/env python3
"""Compare live vs replay market.regime events.

Usage: diff_live_vs_replay.py [--mode MODE] [--compare-event-id] <live_jsonl> <replay_jsonl>
Modes: regime | payload | metrics | strict
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

ALLOWED_MODES = {"regime", "payload", "metrics", "strict"}


def _load_events(path: Path) -> tuple[list[Dict[str, Any]], list[int]]:
    events: list[Dict[str, Any]] = []
    skipped_lines: list[int] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                skipped_lines.append(line_no)
                continue
            if not isinstance(obj, dict):
                skipped_lines.append(line_no)
                continue
            if obj.get("event_type") != "market.regime":
                continue
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                skipped_lines.append(line_no)
                continue
            timestamp = obj.get("timestamp")
            symbol = payload.get("symbol")
            if not isinstance(timestamp, str) or not isinstance(symbol, str):
                skipped_lines.append(line_no)
                continue
            events.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "payload": payload,
                    "event_id": obj.get("event_id"),
                    "line_no": line_no,
                }
            )
    return events, skipped_lines


def _normalize_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _extract_metrics(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return None


def _diff_metrics(live: Dict[str, Any] | None, replay: Dict[str, Any] | None) -> list[str]:
    if live is None and replay is None:
        return []
    if live is None or replay is None:
        return ["metrics_missing"]
    fields = sorted(set(live.keys()) | set(replay.keys()))
    diffs = []
    for field in fields:
        if live.get(field) != replay.get(field):
            diffs.append(field)
    return diffs


def _index_by_key(events: list[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    indexed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for event in events:
        indexed[(event["timestamp"], event["symbol"])] = event
    return indexed


def _compare_regime(
    live: Dict[Tuple[str, str], Dict[str, Any]],
    replay: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    compare_event_id: bool,
) -> list[Dict[str, Any]]:
    mismatches: list[Dict[str, Any]] = []
    all_keys = sorted(set(live.keys()) | set(replay.keys()))
    for key in all_keys:
        live_event = live.get(key)
        replay_event = replay.get(key)
        if live_event is None or replay_event is None:
            mismatches.append(
                {"key": key, "reason": "missing", "live": live_event, "replay": replay_event}
            )
            continue
        live_payload = live_event["payload"]
        replay_payload = replay_event["payload"]
        live_view = {
            "regime": live_payload.get("regime"),
            "confidence": live_payload.get("confidence"),
            "window": live_payload.get("window"),
        }
        replay_view = {
            "regime": replay_payload.get("regime"),
            "confidence": replay_payload.get("confidence"),
            "window": replay_payload.get("window"),
        }
        if compare_event_id:
            live_view["event_id"] = live_event.get("event_id")
            replay_view["event_id"] = replay_event.get("event_id")
        if live_view != replay_view:
            mismatches.append(
                {"key": key, "reason": "regime", "live": live_view, "replay": replay_view}
            )
    return mismatches


def _compare_payload(
    live: Dict[Tuple[str, str], Dict[str, Any]],
    replay: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    compare_event_id: bool,
) -> list[Dict[str, Any]]:
    mismatches: list[Dict[str, Any]] = []
    all_keys = sorted(set(live.keys()) | set(replay.keys()))
    for key in all_keys:
        live_event = live.get(key)
        replay_event = replay.get(key)
        if live_event is None or replay_event is None:
            mismatches.append(
                {"key": key, "reason": "missing", "live": live_event, "replay": replay_event}
            )
            continue
        live_payload = _normalize_payload(live_event["payload"])
        replay_payload = _normalize_payload(replay_event["payload"])
        if live_payload != replay_payload:
            mismatches.append(
                {
                    "key": key,
                    "reason": "payload",
                    "live": live_payload,
                    "replay": replay_payload,
                }
            )
            continue
        if compare_event_id and live_event.get("event_id") != replay_event.get("event_id"):
            mismatches.append(
                {
                    "key": key,
                    "reason": "event_id",
                    "live": live_event.get("event_id"),
                    "replay": replay_event.get("event_id"),
                }
            )
    return mismatches


def _compare_metrics(
    live: Dict[Tuple[str, str], Dict[str, Any]],
    replay: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    compare_event_id: bool,
) -> list[Dict[str, Any]]:
    mismatches: list[Dict[str, Any]] = []
    all_keys = sorted(set(live.keys()) | set(replay.keys()))
    for key in all_keys:
        live_event = live.get(key)
        replay_event = replay.get(key)
        if live_event is None or replay_event is None:
            mismatches.append(
                {"key": key, "reason": "missing", "live": live_event, "replay": replay_event}
            )
            continue
        live_metrics = _extract_metrics(live_event["payload"])
        replay_metrics = _extract_metrics(replay_event["payload"])
        diff_fields = _diff_metrics(live_metrics, replay_metrics)
        if diff_fields:
            mismatches.append(
                {
                    "key": key,
                    "reason": "metrics",
                    "fields": diff_fields,
                    "live": live_metrics,
                    "replay": replay_metrics,
                }
            )
            continue
        if compare_event_id and live_event.get("event_id") != replay_event.get("event_id"):
            mismatches.append(
                {
                    "key": key,
                    "reason": "event_id",
                    "live": live_event.get("event_id"),
                    "replay": replay_event.get("event_id"),
                }
            )
    return mismatches


def _compare_strict(
    live_events: list[Dict[str, Any]],
    replay_events: list[Dict[str, Any]],
    *,
    compare_event_id: bool,
) -> list[Dict[str, Any]]:
    mismatches: list[Dict[str, Any]] = []
    live_indexed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    replay_indexed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    live_missing_tick_ts: list[Dict[str, Any]] = []
    replay_missing_tick_ts: list[Dict[str, Any]] = []

    for event in live_events:
        tick_ts = event["payload"].get("tick_ts")
        if isinstance(tick_ts, str) and tick_ts:
            live_indexed[(event["symbol"], tick_ts)] = event
        else:
            live_missing_tick_ts.append(event)
    for event in replay_events:
        tick_ts = event["payload"].get("tick_ts")
        if isinstance(tick_ts, str) and tick_ts:
            replay_indexed[(event["symbol"], tick_ts)] = event
        else:
            replay_missing_tick_ts.append(event)

    for event in live_missing_tick_ts:
        mismatches.append({"reason": "missing_tick_ts", "live": event, "replay": None})
    for event in replay_missing_tick_ts:
        mismatches.append({"reason": "missing_tick_ts", "live": None, "replay": event})

    all_keys = sorted(set(live_indexed.keys()) | set(replay_indexed.keys()))
    for key in all_keys:
        live_event = live_indexed.get(key)
        replay_event = replay_indexed.get(key)
        if live_event is None or replay_event is None:
            mismatches.append(
                {"key": key, "reason": "missing", "live": live_event, "replay": replay_event}
            )
            continue
        live_payload = live_event["payload"]
        replay_payload = replay_event["payload"]
        if live_payload.get("regime") != replay_payload.get("regime"):
            mismatches.append(
                {
                    "key": key,
                    "reason": "regime",
                    "live": live_payload.get("regime"),
                    "replay": replay_payload.get("regime"),
                }
            )
            continue
        if compare_event_id and live_event.get("event_id") != replay_event.get("event_id"):
            mismatches.append(
                {
                    "key": key,
                    "reason": "event_id",
                    "live": live_event.get("event_id"),
                    "replay": replay_event.get("event_id"),
                }
            )
    return mismatches


def _print_mismatches(mismatches: list[Dict[str, Any]], *, mode: str) -> None:
    if not mismatches:
        return
    print("first 20 mismatches:")
    for mismatch in mismatches[:20]:
        if mode == "strict":
            if "key" in mismatch:
                key = mismatch.get("key")
                if isinstance(key, tuple):
                    symbol, tick_ts = key
                    print(f"- {symbol} {tick_ts} reason={mismatch.get('reason')}")
                else:
                    print(f"- key={key} reason={mismatch.get('reason')}")
            else:
                print(f"- reason={mismatch.get('reason')}")
            live_event = mismatch.get("live")
            replay_event = mismatch.get("replay")
            if isinstance(live_event, dict):
                print(
                    f"  live: {live_event.get('timestamp')} {live_event.get('symbol')} line={live_event.get('line_no')}"
                )
            else:
                print("  live: <missing>")
            if isinstance(replay_event, dict):
                print(
                    f"  replay: {replay_event.get('timestamp')} {replay_event.get('symbol')} line={replay_event.get('line_no')}"
                )
            else:
                print("  replay: <missing>")
        else:
            key = mismatch.get("key")
            if isinstance(key, tuple):
                timestamp, symbol = key
                print(f"- {timestamp} {symbol} reason={mismatch.get('reason')}")
            else:
                print(f"- key={key} reason={mismatch.get('reason')}")
            print(f"  live: {mismatch.get('live')}")
            print(f"  replay: {mismatch.get('replay')}")


def _parse_args(argv: list[str]) -> tuple[str, bool, list[str]]:
    mode = "regime"
    compare_event_id = False
    paths: list[str] = []
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--compare-event-id":
            compare_event_id = True
        elif arg == "--mode":
            if idx + 1 >= len(argv):
                raise ValueError("missing mode value")
            mode = argv[idx + 1]
            idx += 1
        elif arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        else:
            paths.append(arg)
        idx += 1
    return mode, compare_event_id, paths


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        mode, compare_event_id, paths = _parse_args(args)
    except ValueError:
        print("usage: diff_live_vs_replay.py [--mode MODE] [--compare-event-id] <live_jsonl> <replay_jsonl>")
        return 2
    if mode not in ALLOWED_MODES:
        print("usage: diff_live_vs_replay.py [--mode MODE] [--compare-event-id] <live_jsonl> <replay_jsonl>")
        print(f"invalid mode: {mode}")
        return 2
    if len(paths) != 2:
        print("usage: diff_live_vs_replay.py [--mode MODE] [--compare-event-id] <live_jsonl> <replay_jsonl>")
        return 2

    live_path = Path(paths[0])
    replay_path = Path(paths[1])

    live_events, live_skipped = _load_events(live_path)
    replay_events, replay_skipped = _load_events(replay_path)

    if mode == "strict":
        mismatches = _compare_strict(
            live_events,
            replay_events,
            compare_event_id=compare_event_id,
        )
    else:
        live_indexed = _index_by_key(live_events)
        replay_indexed = _index_by_key(replay_events)
        if mode == "payload":
            mismatches = _compare_payload(
                live_indexed,
                replay_indexed,
                compare_event_id=compare_event_id,
            )
        elif mode == "metrics":
            mismatches = _compare_metrics(
                live_indexed,
                replay_indexed,
                compare_event_id=compare_event_id,
            )
        else:
            mismatches = _compare_regime(
                live_indexed,
                replay_indexed,
                compare_event_id=compare_event_id,
            )

    print(f"mismatches: {len(mismatches)}")
    _print_mismatches(mismatches, mode=mode)

    if live_skipped or replay_skipped:
        print(f"skipped lines: live={len(live_skipped)} replay={len(replay_skipped)}")

    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
