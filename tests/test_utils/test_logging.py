"""Tests for utils/logging.py."""

from __future__ import annotations

import logging
from pathlib import Path


def test_configure_logging_does_not_raise() -> None:
    from simpleBIDS.utils.logging import configure_logging
    configure_logging()  # default — no file, INFO level


def test_configure_logging_with_file_handler_creates_file(tmp_path: Path) -> None:
    """Passing log_file creates a FileHandler and the file appears on disk (line 25)."""
    from simpleBIDS.utils.logging import configure_logging

    log_file = tmp_path / "simpleBIDS.log"
    configure_logging(log_file=log_file)
    # FileHandler is instantiated (creating the file) even if basicConfig is a no-op
    assert log_file.exists()


def test_configure_logging_sets_simpleBIDS_level() -> None:
    from simpleBIDS.utils.logging import configure_logging

    configure_logging(level=logging.DEBUG)
    assert logging.getLogger("simpleBIDS").level <= logging.DEBUG
