from __future__ import annotations

import logging
import os
import sys


def configure_logging(name: str = "synthdesk-listener", level: str | None = None) -> logging.Logger:
    lvl = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    logger = logging.getLogger(name)
    logger.setLevel(lvl)
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger
