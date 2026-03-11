"""Infer a BIDS-safe session identifier from DICOM metadata and file paths."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from simpleBIDS.parsers.dicom_parser import DicomMetadata
from simpleBIDS.parsers.path_parser import bids_safe, extract_path_candidates

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{8}$")  # YYYYMMDD


def infer_session(
    metadata: DicomMetadata | None,
    filepath: Path,
    *,
    fallback: str = "01",
) -> str:
    """Return a BIDS-safe session label inferred from available data.

    Priority order:
    1. DICOM ``SeriesDate`` or ``AcquisitionDate`` (YYYYMMDD)
    2. DICOM ``StudyDate``
    3. Date string from file path
    4. Session keyword from file path (``baseline``, ``followup``, ``visit1``, …)
    5. *fallback* value

    Args:
        metadata: Parsed DICOM header metadata, or ``None`` for NIfTI input.
        filepath: Path to the source file or its parent directory.
        fallback: Value to use when no candidate can be found (default ``"01"``).

    Returns:
        BIDS-safe string (alphanumeric only).
    """
    if metadata is not None:
        for date_field in (metadata.series_date, metadata.acquisition_date, metadata.study_date):
            if date_field and _DATE_RE.match(date_field.strip()):
                label = bids_safe(date_field.strip())
                logger.debug("Inferred session '%s' from DICOM date field", label)
                return label

    path_candidates = extract_path_candidates(filepath, mode="session")
    for candidate in path_candidates:
        label = bids_safe(candidate.value.replace("-", ""))
        if label:
            logger.debug("Inferred session '%s' from path (%s)", label, candidate.source)
            return label

    logger.warning("Could not infer session from %s; using '%s'", filepath, fallback)
    return fallback
