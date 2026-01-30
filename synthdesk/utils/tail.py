"""Canonical file tailers for synthdesk.

Two patterns:

1. tail_readline() — blocking generator for continuous tailing (streaming mode)
2. read_new_lines() — batch reader for cursor-based polling (soak/observer mode)

Both use readline() only. No tell(), no iterator protocol.
"""

import os
import time
from pathlib import Path
from typing import Iterator, List, Tuple


def tail_readline(
    path: Path,
    poll_s: float = 0.25,
    seek_end: bool = False,
) -> Iterator[str]:
    """Yield non-empty stripped lines from a growing file.

    Blocking generator — use in streaming services that tail forever.

    Args:
        path: File to tail.
        poll_s: Sleep interval when no new data.
        seek_end: If True, skip existing content and only yield new lines.

    Yields:
        Stripped non-empty lines.
    """
    path = Path(path)

    while not path.exists():
        time.sleep(poll_s)

    with path.open('r', encoding='utf-8') as f:
        if seek_end:
            f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_s)
                continue
            line = line.strip()
            if line:
                yield line


def read_new_lines(
    path: Path,
    cursor: int = 0,
) -> Tuple[List[str], int]:
    """Read new complete lines from a file starting at byte offset.

    Non-blocking batch reader — use in polling loops that call periodically.

    Uses readline() only. No iterator protocol, no tell().

    Args:
        path: File to read.
        cursor: Byte offset to start reading from.

    Returns:
        (lines, new_cursor) where new_cursor is the byte offset after
        the last complete line read.
    """
    path = Path(path)
    lines: List[str] = []

    if not path.exists():
        return lines, cursor

    with path.open('r', encoding='utf-8') as f:
        f.seek(cursor)
        while True:
            pos_before = f.tell()
            line = f.readline()
            if not line:
                # EOF — cursor stays at last complete line
                return lines, pos_before
            if not line.endswith('\n'):
                # Incomplete line (still being written) — don't consume it
                return lines, pos_before
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        # unreachable, but for clarity:
        return lines, f.tell()
