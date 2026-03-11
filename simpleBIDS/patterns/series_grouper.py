"""Group DICOM or NIfTI files into per-series collections."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SeriesGroup:
    """All files belonging to a single imaging series."""

    series_description: str | None
    series_number: int | None
    modality: str | None
    all_files: list[Path]
    representative_file: Path
    file_count: int
    # Populated by inference modules after grouping
    subject_id: str | None = None
    session_id: str | None = None
    # Heuristic suggestions; overridden by user input
    suggested_datatype: str | None = None
    suggested_suffix: str | None = None
    # Staging symlink directory (set by symlink_sorter)
    staging_dir: Path | None = None
    # Extra metadata carried through the pipeline
    extra: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Short filesystem-safe identifier for this series."""
        parts = []
        if self.series_number is not None:
            parts.append(f"{self.series_number:03d}")
        if self.series_description:
            safe = "".join(c if c.isalnum() else "_" for c in self.series_description)
            parts.append(safe[:48])
        return "_".join(parts) or "unknown"


def group_dicom_series(dicom_root: Path) -> list[SeriesGroup]:
    """Walk *dicom_root* and group DICOM files into :class:`SeriesGroup` objects.

    Grouping key: ``(SeriesDescription, SeriesNumber)``. A representative file
    is chosen as the middle file in each sorted group.
    """
    from simpleBIDS.parsers.dicom_parser import walk_dicom_directory

    raw_groups = walk_dicom_directory(dicom_root)
    series_groups: list[SeriesGroup] = []

    for (desc, num), files in raw_groups.items():
        sorted_files = sorted(files)
        representative = sorted_files[len(sorted_files) // 2]

        # Read modality from the representative file
        modality: str | None = None
        try:
            import pydicom
            ds = pydicom.dcmread(str(representative), stop_before_pixels=True)
            modality = str(getattr(ds, "Modality", None) or "").strip() or None
        except Exception:
            logger.debug("Could not read modality from %s", representative)

        series_groups.append(
            SeriesGroup(
                series_description=desc,
                series_number=num,
                modality=modality,
                all_files=sorted_files,
                representative_file=representative,
                file_count=len(sorted_files),
            )
        )

    series_groups.sort(key=lambda g: (g.series_number or 0, g.series_description or ""))
    logger.info("Found %d DICOM series under %s", len(series_groups), dicom_root)
    return series_groups


def group_nifti_files(nifti_root: Path) -> list[SeriesGroup]:
    """Walk *nifti_root* and create one :class:`SeriesGroup` per NIfTI file."""
    from simpleBIDS.parsers.nifti_parser import walk_nifti_directory, parse_nifti

    niftis = walk_nifti_directory(nifti_root)
    series_groups: list[SeriesGroup] = []

    for path in sorted(niftis):
        try:
            meta = parse_nifti(path)
        except Exception:
            logger.warning("Skipping unreadable NIfTI: %s", path)
            continue

        series_groups.append(
            SeriesGroup(
                series_description=meta.series_description or path.stem,
                series_number=None,
                modality=None,
                all_files=[path],
                representative_file=path,
                file_count=1,
                extra={"nifti_metadata": meta},
            )
        )

    logger.info("Found %d NIfTI files under %s", len(series_groups), nifti_root)
    return series_groups


def group_series(root: Path, *, mode: str = "auto") -> list[SeriesGroup]:
    """Top-level entry point: group all series found under *root*.

    Args:
        root: Root directory containing raw imaging data.
        mode: ``"dicom"``, ``"nifti"``, or ``"auto"`` (detect by content).

    Returns:
        Combined list of :class:`SeriesGroup` objects.
    """
    if mode == "dicom":
        return group_dicom_series(root)
    if mode == "nifti":
        return group_nifti_files(root)

    # Auto-detect
    from simpleBIDS.utils.filesystem import iter_files
    has_dcm = any(True for _ in iter_files(root, suffixes={".dcm", ""}, limit=1))
    has_nii = any(True for _ in iter_files(root, suffixes={".nii", ".gz"}, limit=1))

    groups: list[SeriesGroup] = []
    if has_dcm:
        groups += group_dicom_series(root)
    if has_nii and not has_dcm:
        groups += group_nifti_files(root)
    return groups
