"""Filesystem traversal utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


def iter_files(
    root: Path,
    *,
    suffixes: set[str] | None = None,
    limit: int | None = None,
) -> Iterator[Path]:
    """Recursively yield files under *root*, optionally filtered by suffix.

    Args:
        root: Directory to walk.
        suffixes: If provided, only yield files whose ``suffix`` (lowercased)
            is in this set. Pass ``{""}`` to match extension-less files.
        limit: Stop after yielding this many files (useful for existence checks).

    Yields:
        :class:`pathlib.Path` objects for each matching file.
    """
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        yield path
        count += 1
        if limit is not None and count >= limit:
            return


def ensure_dir(path: Path) -> Path:
    """Create *path* as a directory (including parents) and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_stem(name: str) -> str:
    """Return a filesystem-safe version of *name* (spaces → underscores)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
