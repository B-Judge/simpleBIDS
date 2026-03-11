"""DICOM header extraction and series-level metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pydicom

logger = logging.getLogger(__name__)

# DICOM tags to extract. Tags absent from a file are silently skipped.
_TAGS = (
    "SeriesDescription",
    "SeriesNumber",
    "Modality",
    "PatientID",
    "PatientName",
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "StudyDescription",
    "InstitutionName",
    "ImageType",
    "ProtocolName",
)


@dataclass
class DicomMetadata:
    """Metadata extracted from a single DICOM series (one representative file)."""

    representative_file: Path
    file_count: int
    series_description: str | None = None
    series_number: int | None = None
    modality: str | None = None
    patient_id: str | None = None
    patient_name: str | None = None
    study_date: str | None = None
    series_date: str | None = None
    acquisition_date: str | None = None
    study_description: str | None = None
    institution_name: str | None = None
    image_type: list[str] = field(default_factory=list)
    protocol_name: str | None = None


def parse_dicom_file(path: Path) -> DicomMetadata:
    """Read header tags from a single DICOM file.

    Only the header is read (``stop_before_pixels=True``).
    Missing or malformed tags are logged as warnings and omitted.
    """
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True)
    except Exception as exc:
        logger.warning("Failed to read DICOM file %s: %s", path, exc)
        raise

    def _get(tag: str) -> str | None:
        try:
            value = getattr(ds, tag, None)
            return str(value).strip() if value is not None else None
        except Exception:
            logger.warning("Could not read tag %s from %s", tag, path)
            return None

    image_type_raw = getattr(ds, "ImageType", None)
    image_type = list(image_type_raw) if image_type_raw is not None else []

    series_number_raw = _get("SeriesNumber")
    try:
        series_number = int(series_number_raw) if series_number_raw else None
    except ValueError:
        series_number = None

    return DicomMetadata(
        representative_file=path,
        file_count=1,
        series_description=_get("SeriesDescription"),
        series_number=series_number,
        modality=_get("Modality"),
        patient_id=_get("PatientID"),
        patient_name=_get("PatientName"),
        study_date=_get("StudyDate"),
        series_date=_get("SeriesDate"),
        acquisition_date=_get("AcquisitionDate"),
        study_description=_get("StudyDescription"),
        institution_name=_get("InstitutionName"),
        image_type=image_type,
        protocol_name=_get("ProtocolName"),
    )


def parse_dicom_series(dicom_files: list[Path]) -> DicomMetadata:
    """Build a single :class:`DicomMetadata` for a collection of DICOM files.

    Reads only one representative file (the middle of the sorted list) to
    avoid loading every slice's headers. The ``file_count`` field reflects the
    full number of files in the series.
    """
    if not dicom_files:
        raise ValueError("dicom_files must not be empty")

    sorted_files = sorted(dicom_files)
    representative = sorted_files[len(sorted_files) // 2]
    metadata = parse_dicom_file(representative)
    metadata.file_count = len(sorted_files)
    return metadata


def walk_dicom_directory(root: Path) -> dict[tuple[str | None, int | None], list[Path]]:
    """Recursively find all DICOM files under *root* and group them by series.

    Returns a mapping of ``(series_description, series_number)`` → list of
    file paths. Files that cannot be read as DICOM are skipped with a warning.
    """
    from simpleBIDS.utils.filesystem import iter_files

    groups: dict[tuple[str | None, int | None], list[Path]] = {}
    for path in iter_files(root, suffixes={".dcm", ""}):
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
        except Exception:
            logger.debug("Skipping non-DICOM file: %s", path)
            continue

        desc = str(getattr(ds, "SeriesDescription", None) or "").strip() or None
        num_raw = getattr(ds, "SeriesNumber", None)
        try:
            num = int(num_raw) if num_raw is not None else None
        except (ValueError, TypeError):
            num = None

        key = (desc, num)
        groups.setdefault(key, []).append(path)

    return groups
