"""Logging utilities for SynthDesk listener."""

import logging
from logging.handlers import RotatingFileHandler
from typing import Optional, Union


def configure_logging(
    level: Union[int, str] = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure a timestamped logger with stdout and optional rotating file.

    Args:
        level: Logging level name or numeric value.
        log_file: Optional path for a rotating file handler.
        max_bytes: Maximum bytes per log file before rotation.
        backup_count: Number of rotated files to keep.
    """
    logger = logging.getLogger("synthdesk_listener")
    if logger.handlers:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


__all__ = ["configure_logging"]

