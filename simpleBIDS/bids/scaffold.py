"""Generate a valid BIDS project directory structure (like dcm2bids_scaffold)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BIDS_VERSION = "1.9.0"

_TOP_LEVEL_DIRS = ["code", "derivatives", "sourcedata"]

_DATASET_DESCRIPTION_DEFAULTS = {
    "BIDSVersion": _BIDS_VERSION,
    "Name": "",
    "Authors": [],
    "HowToAcknowledge": "",
    "License": "",
}

_PARTICIPANTS_HEADERS = ["participant_id"]

_README_TEMPLATE = """\
# {name}

This dataset was organized with simpleBIDS.
"""


def scaffold_bids(
    bids_root: Path,
    *,
    dataset_name: str = "Untitled Dataset",
    authors: list[str] | None = None,
    overwrite: bool = False,
) -> None:
    """Create a minimal valid BIDS project structure at *bids_root*.

    Existing files are never overwritten unless *overwrite* is ``True``.
    Directories are always created (``mkdir`` is idempotent).

    Args:
        bids_root: Root directory for the BIDS project.
        dataset_name: Value for ``dataset_description.json["Name"]``.
        authors: List of author strings for ``dataset_description.json``.
        overwrite: If ``True``, overwrite existing top-level files.
    """
    bids_root.mkdir(parents=True, exist_ok=True)

    # Subdirectories
    for dirname in _TOP_LEVEL_DIRS:
        (bids_root / dirname).mkdir(exist_ok=True)

    # dataset_description.json
    _write_json(
        bids_root / "dataset_description.json",
        {**_DATASET_DESCRIPTION_DEFAULTS, "Name": dataset_name, "Authors": authors or []},
        overwrite=overwrite,
    )

    # participants.tsv
    _write_text(
        bids_root / "participants.tsv",
        "\t".join(_PARTICIPANTS_HEADERS) + "\n",
        overwrite=overwrite,
    )

    # participants.json
    _write_json(
        bids_root / "participants.json",
        {"participant_id": {"Description": "Unique participant identifier"}},
        overwrite=overwrite,
    )

    # README
    _write_text(
        bids_root / "README",
        _README_TEMPLATE.format(name=dataset_name),
        overwrite=overwrite,
    )

    # .bidsignore
    _write_text(
        bids_root / ".bidsignore",
        ".simpleBIDS_staging/\ncode/\n",
        overwrite=overwrite,
    )

    logger.info("BIDS scaffold created at %s", bids_root)


def _write_json(path: Path, data: dict, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        logger.debug("Skipping existing file: %s", path)
        return
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug("Wrote %s", path)


def _write_text(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        logger.debug("Skipping existing file: %s", path)
        return
    path.write_text(content, encoding="utf-8")
    logger.debug("Wrote %s", path)
