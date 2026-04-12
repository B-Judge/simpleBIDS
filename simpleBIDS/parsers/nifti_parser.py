"""NIfTI header and JSON sidecar parsing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import nibabel as nib
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class NiftiMetadata:
    """Metadata extracted from a NIfTI file and its optional JSON sidecar."""

    filepath: Path
    shape: tuple[int, ...]
    voxel_size: tuple[float, ...]
    tr: float | None = None
    phase_encoding_direction: str | None = None
    task_name: str | None = None
    series_description: str | None = None
    sidecar: dict = field(default_factory=dict)


def parse_nifti(path: Path) -> NiftiMetadata:
    """Load header information from a NIfTI file.

    Companion JSON sidecars (same stem, ``.json`` extension) are parsed when
    present. Missing sidecar fields are silently omitted.
    """
    try:
        img = nib.load(str(path))
    except Exception as exc:
        logger.warning("Failed to load NIfTI %s: %s", path, exc)
        raise

    header = img.header
    shape = tuple(int(d) for d in img.shape)
    zooms = header.get_zooms()
    voxel_size = tuple(float(z) for z in zooms[:3])

    # TR lives in the 4th zoom dimension for 4D images
    tr: float | None = None
    if len(zooms) >= 4 and zooms[3] > 0:
        tr = float(zooms[3])

    sidecar = _load_sidecar(path)

    return NiftiMetadata(
        filepath=path,
        shape=shape,
        voxel_size=voxel_size,
        tr=sidecar.get("RepetitionTime", tr),
        phase_encoding_direction=sidecar.get("PhaseEncodingDirection"),
        task_name=sidecar.get("TaskName"),
        series_description=sidecar.get("SeriesDescription"),
        sidecar=sidecar,
    )


def _load_sidecar(nifti_path: Path) -> dict:
    """Load the JSON sidecar for a NIfTI file if it exists.

    Handles both ``.nii`` (sidecar is ``<stem>.json``) and ``.nii.gz``
    (sidecar is ``<stem-without-.nii.gz>.json``).
    """
    name = nifti_path.name
    if name.endswith(".nii.gz"):
        sidecar_path = nifti_path.parent / (name[: -len(".nii.gz")] + ".json")
    else:
        sidecar_path = nifti_path.with_suffix(".json")
    if sidecar_path.exists():
        try:
            return json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse JSON sidecar %s: %s", sidecar_path, exc)
    return {}


def walk_nifti_directory(root: Path) -> list[Path]:
    """Recursively find all NIfTI files (``.nii``, ``.nii.gz``) under *root*."""
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(".nii.gz") or name.endswith(".nii"):
            result.append(path)
    return result
