"""Structured logging configuration for simpleBIDS."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> None:
    """Set up root logger with a consistent format.

    Args:
        level: Logging level for the ``simpleBIDS`` logger (default INFO).
        log_file: If provided, also write logs to this file.
    """
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(handlers=handlers, format=fmt, datefmt=datefmt, level=logging.WARNING)

    # Only raise verbosity for our own package
    logging.getLogger("simpleBIDS").setLevel(level)
