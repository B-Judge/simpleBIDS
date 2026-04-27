"""DICOM header extraction and series-level metadata.

Scanning strategy
-----------------
Large datasets contain thousands of DICOM files.  We use a two-pass approach
to keep I/O minimal:

1. **First pass** — read only the handful of tags needed for grouping from
   every file using ``specific_tags``.  This skips the vast majority of the
   DICOM header and is dramatically faster than a full read.

2. **Representative read** — for each discovered series, read the *full* header
   (stop before pixels) of one file (the middle slice by InstanceNumber) to
   populate all ``DicomMetadata`` fields.

All public functions raise on hard errors and log at ``DEBUG`` for expected
misses (files that are not DICOM, tags that are absent).
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import pydicom
from pydicom.tag import Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tags read in the fast first pass (grouping only)
# ---------------------------------------------------------------------------
_FIRST_PASS_TAGS = [
    "SOPClassUID",
    "SOPInstanceUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDescription",
    "InstanceNumber",
    "Modality",
    "TemporalPositionIdentifier",
    "RadiopharmaceuticalInformationSequence",
]

# Known DICOM file extensions (lower-cased).  Files with no extension are also
# attempted.  Anything else is skipped in the fast scan.
_DICOM_EXTENSIONS = {".dcm", ".ima", ".img", ".dicom", ""}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DicomMetadata:
    """All header metadata extracted from one representative DICOM file."""

    # --- Identity ----------------------------------------------------------
    representative_file: Path
    file_count: int
    series_instance_uid: str | None = None
    study_instance_uid: str | None = None
    sop_instance_uid: str | None = None
    sop_class_uid: str | None = None

    # --- Series-level descriptors ------------------------------------------
    series_description: str | None = None
    series_number: int | None = None
    modality: str | None = None
    protocol_name: str | None = None
    study_description: str | None = None
    institution_name: str | None = None
    image_type: list[str] = field(default_factory=list)

    # --- Patient / study ---------------------------------------------------
    patient_id: str | None = None
    patient_name: str | None = None
    study_date: str | None = None
    series_date: str | None = None
    acquisition_date: str | None = None

    # --- Slice / instance --------------------------------------------------
    instance_number: int | None = None
    acquisition_number: int | None = None
    slice_location: float | None = None

    # --- MR timing parameters ---------------------------------------------
    repetition_time: float | None = None   # ms
    echo_time: float | None = None         # ms
    inversion_time: float | None = None    # ms
    flip_angle: float | None = None        # degrees

    # --- Geometry ----------------------------------------------------------
    rows: int | None = None
    columns: int | None = None
    slice_thickness: float | None = None   # mm
    pixel_spacing: tuple[float, float] | None = None  # (row_spacing, col_spacing) mm

    # --- Functional / diffusion --------------------------------------------
    number_of_temporal_positions: int | None = None
    diffusion_b_value: float | None = None

    # --- PET ---------------------------------------------------------------
    tracer: str | None = None  # Radiopharmaceutical from RadiopharmaceuticalInformationSequence

    # --- Flags -------------------------------------------------------------
    is_localizer: bool = False


@dataclass
class DicomSeries:
    """One imaging series: representative metadata + all sorted file paths."""

    metadata: DicomMetadata
    all_files: list[Path]        # sorted by InstanceNumber (then filename)
    series_key: str              # SeriesInstanceUID or composite fallback key


# ---------------------------------------------------------------------------
# Single-file parsing
# ---------------------------------------------------------------------------

def parse_dicom_file(path: Path) -> DicomMetadata:
    """Read the full header from *path* and return a :class:`DicomMetadata`.

    Pixel data is never read (``stop_before_pixels=True``).
    Missing or malformed tags are silently omitted (logged at DEBUG).
    Raises on unreadable files.
    """
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
    except Exception as exc:
        logger.warning("Cannot read DICOM file %s: %s", path, exc)
        raise

    def _str(tag: str) -> str | None:
        try:
            val = getattr(ds, tag, None)
            return str(val).strip() if val is not None else None
        except Exception:
            logger.debug("Unreadable tag %s in %s", tag, path)
            return None

    def _float(tag: str) -> float | None:
        raw = _str(tag)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _int(tag: str) -> int | None:
        raw = _str(tag)
        if raw is None:
            return None
        try:
            return int(float(raw))
        except ValueError:
            return None

    # ImageType is a sequence of strings
    image_type_raw = getattr(ds, "ImageType", None)
    image_type: list[str] = list(image_type_raw) if image_type_raw is not None else []

    # PixelSpacing is a sequence of two values (row spacing, column spacing)
    pixel_spacing: tuple[float, float] | None = None
    ps_raw = getattr(ds, "PixelSpacing", None)
    if ps_raw is not None and len(ps_raw) >= 2:
        try:
            pixel_spacing = (float(ps_raw[0]), float(ps_raw[1]))
        except (ValueError, TypeError):
            pass

    # DiffusionBValue — standard tag (0018,9087), also try GE private (0019,100c)
    b_value: float | None = _float("DiffusionBValue")
    if b_value is None:
        try:
            b_value = float(ds[0x0019, 0x100C].value)
        except (KeyError, TypeError, ValueError):
            pass

    is_loc = _is_localizer_raw(image_type, _str("SeriesDescription"))

    # PET tracer name from RadiopharmaceuticalInformationSequence
    tracer: str | None = None
    if _str("Modality") == "PT":
        try:
            radio_seq = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
            if radio_seq and len(radio_seq) > 0:
                t = str(getattr(radio_seq[0], "Radiopharmaceutical", "") or "").strip()
                tracer = t or None
        except Exception:
            logger.debug("Could not read tracer info from %s", path)

    return DicomMetadata(
        representative_file=path,
        file_count=1,
        # Identity
        series_instance_uid=_str("SeriesInstanceUID"),
        study_instance_uid=_str("StudyInstanceUID"),
        sop_instance_uid=_str("SOPInstanceUID"),
        sop_class_uid=_str("SOPClassUID"),
        # Series descriptors
        series_description=_str("SeriesDescription"),
        series_number=_int("SeriesNumber"),
        modality=_str("Modality"),
        protocol_name=_str("ProtocolName"),
        study_description=_str("StudyDescription"),
        institution_name=_str("InstitutionName"),
        image_type=image_type,
        # Patient / study
        patient_id=_str("PatientID"),
        patient_name=_str("PatientName"),
        study_date=_str("StudyDate"),
        series_date=_str("SeriesDate"),
        acquisition_date=_str("AcquisitionDate"),
        # Slice
        instance_number=_int("InstanceNumber"),
        acquisition_number=_int("AcquisitionNumber"),
        slice_location=_float("SliceLocation"),
        # MR timing
        repetition_time=_float("RepetitionTime"),
        echo_time=_float("EchoTime"),
        inversion_time=_float("InversionTime"),
        flip_angle=_float("FlipAngle"),
        # Geometry
        rows=_int("Rows"),
        columns=_int("Columns"),
        slice_thickness=_float("SliceThickness"),
        pixel_spacing=pixel_spacing,
        # Functional / diffusion
        number_of_temporal_positions=_int("NumberOfTemporalPositions"),
        diffusion_b_value=b_value,
        # PET
        tracer=tracer,
        # Flags
        is_localizer=is_loc,
    )


def parse_dicom_series(dicom_files: list[Path]) -> DicomMetadata:
    """Build a single :class:`DicomMetadata` from a collection of files.

    Reads only the middle file (sorted by name).  ``file_count`` reflects the
    full collection size.
    """
    if not dicom_files:
        raise ValueError("dicom_files must not be empty")
    sorted_files = sorted(dicom_files)
    representative = sorted_files[len(sorted_files) // 2]
    meta = parse_dicom_file(representative)
    meta.file_count = len(sorted_files)
    return meta


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def scan_dicom_directory(
    root: Path,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    n_workers: int = 4,
) -> list[DicomSeries]:
    """Recursively scan *root* and return one :class:`DicomSeries` per series.

    Uses a fast two-pass strategy:

    1. Read minimal grouping tags from every candidate file in parallel.
    2. Read the full header of one representative file per group.

    Args:
        root: Directory containing raw DICOM data (searched recursively).
        progress_callback: Called as ``callback(n_done, n_total)`` after each
            file is processed in the first pass.
        n_workers: Thread-pool size for parallel first-pass reads.

    Returns:
        List of :class:`DicomSeries`, sorted by series number then description.
    """
    candidate_files = list(_iter_candidate_files(root))
    total = len(candidate_files)
    if total == 0:
        logger.info("No candidate DICOM files found under %s", root)
        return []

    logger.info("Scanning %d candidate files under %s", total, root)

    # --- First pass: group files by series ---------------------------------
    # Maps series_key → list of (instance_number, temporal_pos, path)
    groups: dict[str, list[tuple[int, int, Path]]] = {}
    # Also keep one raw first-pass dataset per series for the key metadata
    key_meta: dict[str, dict] = {}

    done = 0

    def _read_first(path: Path) -> tuple[str, int, int, Path, dict] | None:
        """Return (series_key, instance_number, temporal_pos, path, raw_meta) or None."""
        try:
            ds = pydicom.dcmread(
                str(path),
                stop_before_pixels=True,
                specific_tags=_FIRST_PASS_TAGS,
                force=False,
            )
        except Exception:
            logger.debug("Skipping non-DICOM file: %s", path)
            return None

        series_key, raw = _extract_series_key(ds, path)
        inst = _safe_int(getattr(ds, "InstanceNumber", None)) or 0
        # TemporalPositionIdentifier identifies which volume in a 4D series (1-indexed).
        # Default to 1 so 3D series are treated as single-volume.
        temporal_pos = _safe_int(getattr(ds, "TemporalPositionIdentifier", None)) or 1
        return series_key, inst, temporal_pos, path, raw

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_read_first, f): f for f in candidate_files}
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            result = future.result()
            if result is None:
                continue
            series_key, inst, temporal_pos, path, raw = result
            groups.setdefault(series_key, []).append((inst, temporal_pos, path))
            if series_key not in key_meta:
                key_meta[series_key] = raw

    # --- Second pass: read full metadata for representative of each group --
    series_list: list[DicomSeries] = []
    for series_key, inst_tp_file_triples in groups.items():
        # Sort all files by (InstanceNumber, filename) for the full file list
        sorted_triples = sorted(inst_tp_file_triples, key=lambda x: (x[0], str(x[2])))
        sorted_files = [p for _, _, p in sorted_triples]

        # For the representative file, prefer the last temporal position so that
        # the GUI shows the final volume of 4D series (more informative for fMRI,
        # dynamic PET, and multi-echo acquisitions than a middle volume).
        max_tp = max(tp for _, tp, _ in inst_tp_file_triples)
        last_vol = [(i, tp, p) for i, tp, p in inst_tp_file_triples if tp == max_tp]
        last_vol.sort(key=lambda x: (x[0], str(x[2])))
        representative = last_vol[len(last_vol) // 2][2]

        try:
            meta = parse_dicom_file(representative)
        except Exception as exc:
            logger.warning("Could not read representative for series %s: %s", series_key, exc)
            # Fall back to first-pass data for a minimal metadata object
            raw = key_meta.get(series_key, {})
            meta = _meta_from_first_pass(raw, representative, len(sorted_files))

        meta.file_count = len(sorted_files)
        series_list.append(DicomSeries(
            metadata=meta,
            all_files=sorted_files,
            series_key=series_key,
        ))
        logger.debug(
            "Series '%s' (%s): %d files",
            meta.series_description, series_key[:16], len(sorted_files),
        )

    series_list.sort(key=lambda s: (s.metadata.series_number or 0, s.metadata.series_description or ""))
    logger.info("Found %d DICOM series under %s", len(series_list), root)
    return series_list


def walk_dicom_directory(root: Path) -> dict[tuple[str | None, int | None], list[Path]]:
    """Compatibility wrapper — returns the old ``(desc, num) → files`` mapping.

    New code should call :func:`scan_dicom_directory` instead, which groups
    by ``(StudyInstanceUID, SeriesDescription)`` and returns richer metadata.
    """
    series_list = scan_dicom_directory(root, n_workers=1)
    result: dict[tuple[str | None, int | None], list[Path]] = {}
    for s in series_list:
        key = (s.metadata.series_description, s.metadata.series_number)
        result[key] = s.all_files
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_candidate_files(root: Path) -> Iterator[Path]:
    """Yield files that could be DICOM based on extension (or lack thereof)."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in _DICOM_EXTENSIONS:
            yield path


def _extract_series_key(ds: pydicom.Dataset, path: Path) -> tuple[str, dict]:
    """Derive a grouping key based on StudyInstanceUID + SeriesDescription.

    All acquisitions of the same sequence within one scanning session share
    the same StudyInstanceUID and SeriesDescription, so they are merged into
    a single :class:`DicomSeries`.  This lets users label e.g. "BOLD_rest"
    once rather than separately for every run.

    For PET series the radiotracer name is appended so that datasets acquired
    with different tracers remain as separate groups even if the description
    happens to be identical.

    Fallback when SeriesDescription is absent:
    1. ``(StudyInstanceUID, SeriesNumber)``
    2. ``(parent directory, SeriesNumber)``
    """
    raw = {
        "SeriesInstanceUID": str(getattr(ds, "SeriesInstanceUID", "") or "").strip(),
        "StudyInstanceUID": str(getattr(ds, "StudyInstanceUID", "") or "").strip(),
        "SeriesNumber": _safe_int(getattr(ds, "SeriesNumber", None)),
        "SeriesDescription": str(getattr(ds, "SeriesDescription", "") or "").strip(),
        "Modality": str(getattr(ds, "Modality", "") or "").strip(),
        "Tracer": "",
    }

    # For PET: include tracer so different radiotracers stay as separate groups
    if raw["Modality"] == "PT":
        try:
            radio_seq = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
            if radio_seq and len(radio_seq) > 0:
                raw["Tracer"] = str(
                    getattr(radio_seq[0], "Radiopharmaceutical", "") or ""
                ).strip()
        except Exception:
            pass

    study = raw["StudyInstanceUID"]
    desc = raw["SeriesDescription"]
    tracer = raw["Tracer"]

    if desc:
        parts = [p for p in [study, desc, tracer] if p]
        return "::".join(parts), raw

    # Fallback when no description
    if study and raw["SeriesNumber"] is not None:
        return f"{study}::{raw['SeriesNumber']}", raw

    return f"{path.parent}::{raw['SeriesNumber']}", raw


def _meta_from_first_pass(raw: dict, path: Path, file_count: int) -> DicomMetadata:
    """Build a minimal DicomMetadata from first-pass tag data."""
    return DicomMetadata(
        representative_file=path,
        file_count=file_count,
        series_instance_uid=raw.get("SeriesInstanceUID") or None,
        study_instance_uid=raw.get("StudyInstanceUID") or None,
        series_description=raw.get("SeriesDescription") or None,
        series_number=raw.get("SeriesNumber"),
        modality=raw.get("Modality") or None,
        tracer=raw.get("Tracer") or None,
    )


_LOCALIZER_RE = re.compile(
    r"(?i)\b(localizer|localiser|scout|aahead_scout|surve[yt]|3.?plane|planning"
    r"|prescr|topogram|calibr|derived)",
)


def _is_localizer_raw(image_type: list[str], series_description: str | None) -> bool:
    """Return True if the series appears to be a localizer or scout scan."""
    if "LOCALIZER" in [t.upper() for t in image_type]:
        return True
    if series_description and _LOCALIZER_RE.search(series_description):
        return True
    return False


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return None
