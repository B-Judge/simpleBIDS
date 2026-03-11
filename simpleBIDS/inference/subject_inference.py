"""Infer a BIDS-safe subject identifier from DICOM metadata and file paths."""

from __future__ import annotations

import logging
from pathlib import Path

from simpleBIDS.parsers.dicom_parser import DicomMetadata
from simpleBIDS.parsers.path_parser import bids_safe, extract_path_candidates

logger = logging.getLogger(__name__)


def infer_subject(
    metadata: DicomMetadata | None,
    filepath: Path,
    *,
    fallback: str = "unknown",
) -> str:
    """Return a BIDS-safe subject label inferred from available data.

    Priority order:
    1. DICOM ``PatientID`` (cleaned)
    2. DICOM ``PatientName`` (if PatientID is absent or looks generic)
    3. Best regex match from the file path
    4. *fallback* value

    Args:
        metadata: Parsed DICOM header metadata, or ``None`` for NIfTI input.
        filepath: Path to the source file or its parent directory.
        fallback: Value to use when no candidate can be found.

    Returns:
        BIDS-safe string (alphanumeric only, no spaces or special characters).
    """
    candidates: list[str] = []

    if metadata is not None:
        if metadata.patient_id and not _is_generic(metadata.patient_id):
            candidates.append(bids_safe(metadata.patient_id))
        if metadata.patient_name and not _is_generic(str(metadata.patient_name)):
            candidates.append(bids_safe(str(metadata.patient_name)))

    path_candidates = extract_path_candidates(filepath, mode="subject")
    candidates += [bids_safe(c.value) for c in path_candidates]

    # Return first non-empty candidate
    for candidate in candidates:
        if candidate:
            logger.debug("Inferred subject '%s' from %s", candidate, filepath)
            return candidate

    logger.warning("Could not infer subject from %s; using '%s'", filepath, fallback)
    return fallback


def _is_generic(value: str) -> bool:
    """Return True if the value looks like a placeholder rather than a real ID."""
    generic_tokens = {"anonymous", "anon", "unknown", "test", "phantom", "n/a", "na"}
    return value.strip().lower() in generic_tokens or value.strip() in {"", "0", "00"}
