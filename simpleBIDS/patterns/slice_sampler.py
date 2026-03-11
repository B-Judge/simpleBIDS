"""Extract a representative 2D image slice from a DICOM series or NIfTI file."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def sample_slice(representative_file: Path) -> np.ndarray:
    """Return a normalized 2D uint8 array suitable for display.

    For DICOM files, reads pixel data from the given file.
    For NIfTI files, extracts the middle axial slice.
    Pixel values are rescaled to [0, 255] using 1st–99th percentile clipping.

    Args:
        representative_file: Path to a single DICOM file or a NIfTI file.

    Returns:
        2D ``numpy.ndarray`` of dtype ``uint8``.

    Raises:
        ValueError: If the file type is unrecognised or pixel data is unavailable.
    """
    suffix = representative_file.suffix.lower()
    if suffix in {".nii", ".gz"} or ".nii" in representative_file.name:
        return _sample_nifti(representative_file)
    return _sample_dicom(representative_file)


def _sample_dicom(path: Path) -> np.ndarray:
    import pydicom

    ds = pydicom.dcmread(str(path))
    try:
        pixels = ds.pixel_array.astype(np.float32)
    except Exception as exc:
        raise ValueError(f"Could not read pixel data from {path}: {exc}") from exc

    if pixels.ndim == 3:
        # Multi-frame: take middle frame
        pixels = pixels[pixels.shape[0] // 2]

    return _normalize(pixels)


def _sample_nifti(path: Path) -> np.ndarray:
    import nibabel as nib

    img = nib.load(str(path))
    data = np.asarray(img.dataobj, dtype=np.float32)

    # Collapse to 3D
    if data.ndim == 4:
        data = data[..., data.shape[3] // 2]

    # Take middle axial slice
    mid = data.shape[2] // 2
    slice_2d = data[:, :, mid]

    # Rotate to standard radiological orientation
    slice_2d = np.rot90(slice_2d)
    return _normalize(slice_2d)


def _normalize(arr: np.ndarray) -> np.ndarray:
    """Clip to 1st–99th percentile then rescale to uint8."""
    p_low = float(np.percentile(arr, 1))
    p_high = float(np.percentile(arr, 99))
    if p_high == p_low:
        return np.zeros(arr.shape, dtype=np.uint8)
    clipped = np.clip(arr, p_low, p_high)
    scaled = (clipped - p_low) / (p_high - p_low) * 255.0
    return scaled.astype(np.uint8)
