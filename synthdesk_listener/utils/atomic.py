import json, os, csv
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def safe_append_text(path: Path, line: str) -> None:
    """
    Append a single line of text to a log file, flushing to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        if not line.endswith("\n"):
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def safe_append_csv(path: Path, row, header=None) -> None:
    """
    Append a single CSV row, writing a header if the file is new.
    `row` and `header` are sequences.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if (not exists) and header:
            writer.writerow(header)
        writer.writerow(row)
        fh.flush()
        os.fsync(fh.fileno())
