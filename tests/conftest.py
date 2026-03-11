"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_bids_root(tmp_path: Path) -> Path:
    """An empty temporary directory for BIDS output."""
    return tmp_path / "bids"


@pytest.fixture
def tmp_raw_dir(tmp_path: Path) -> Path:
    """An empty temporary directory simulating a raw data source."""
    d = tmp_path / "raw"
    d.mkdir()
    return d
