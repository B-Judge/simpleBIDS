"""Tests for patterns/slice_sampler.py."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers — synthetic DICOM with pixel data and NIfTI
# ---------------------------------------------------------------------------


def _make_dicom_with_pixels(
    path: Path,
    rows: int = 32,
    cols: int = 32,
    multiframe: bool = False,
) -> Path:
    """Create a minimal DICOM file that has readable pixel data."""
    import pydicom
    import pydicom.uid
    from pydicom.dataset import FileDataset

    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0

    if multiframe:
        n_frames = 6
        ds.NumberOfFrames = n_frames
        ds.Rows = rows
        ds.Columns = cols
        pixels = np.arange(rows * cols * n_frames, dtype=np.uint16)
    else:
        ds.Rows = rows
        ds.Columns = cols
        pixels = np.arange(rows * cols, dtype=np.uint16)

    ds.PixelData = pixels.tobytes()
    pydicom.dcmwrite(str(path), ds)
    return path


def _make_nifti_3d(path: Path, shape: tuple = (32, 32, 20)) -> Path:
    import nibabel as nib

    data = np.random.default_rng(42).random(shape).astype(np.float32) * 1000
    img = nib.Nifti1Image(data, np.eye(4))
    nib.save(img, str(path))
    return path


def _make_nifti_4d(path: Path, shape: tuple = (32, 32, 20, 10)) -> Path:
    import nibabel as nib

    data = np.random.default_rng(0).random(shape).astype(np.float32) * 1000
    img = nib.Nifti1Image(data, np.eye(4))
    nib.save(img, str(path))
    return path


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


def test_normalize_returns_uint8() -> None:
    from simpleBIDS.patterns.slice_sampler import _normalize

    arr = np.linspace(0, 1000, 100, dtype=np.float32).reshape(10, 10)
    result = _normalize(arr)
    assert result.dtype == np.uint8


def test_normalize_flat_array_returns_zeros() -> None:
    from simpleBIDS.patterns.slice_sampler import _normalize

    arr = np.full((10, 10), 500.0, dtype=np.float32)
    result = _normalize(arr)
    assert np.all(result == 0)


def test_normalize_output_range_is_0_to_255() -> None:
    from simpleBIDS.patterns.slice_sampler import _normalize

    arr = np.random.default_rng(1).random((20, 20)).astype(np.float32) * 4096
    result = _normalize(arr)
    assert result.min() >= 0
    assert result.max() <= 255


def test_normalize_preserves_shape() -> None:
    from simpleBIDS.patterns.slice_sampler import _normalize

    arr = np.random.default_rng(2).random((64, 48)).astype(np.float32)
    assert _normalize(arr).shape == (64, 48)


# ---------------------------------------------------------------------------
# _sample_dicom
# ---------------------------------------------------------------------------


def test_sample_dicom_returns_2d_uint8(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_dicom

    dcm = _make_dicom_with_pixels(tmp_path / "test.dcm")
    result = _sample_dicom(dcm)
    assert result.ndim == 2
    assert result.dtype == np.uint8


def test_sample_dicom_shape_matches_rows_cols(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_dicom

    dcm = _make_dicom_with_pixels(tmp_path / "test.dcm", rows=24, cols=16)
    result = _sample_dicom(dcm)
    assert result.shape == (24, 16)


def test_sample_dicom_multiframe_returns_2d(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_dicom

    dcm = _make_dicom_with_pixels(tmp_path / "multi.dcm", multiframe=True)
    result = _sample_dicom(dcm)
    assert result.ndim == 2


def test_sample_dicom_multiframe_4d_uses_last_volume(tmp_path: Path) -> None:
    """Multi-frame 4D DICOM: last temporal volume must be selected."""
    import pydicom
    import pydicom.uid
    from pydicom.dataset import FileDataset
    from simpleBIDS.patterns.slice_sampler import _sample_dicom

    rows, cols, n_vols, n_slices = 16, 16, 3, 4
    n_frames = n_vols * n_slices

    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = FileDataset(str(tmp_path / "4d.dcm"), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.NumberOfFrames = n_frames
    ds.NumberOfTemporalPositions = n_vols
    ds.Rows = rows
    ds.Columns = cols

    # Volume-first ordering: frames 0..3 = vol1 (flat 0), frames 4..7 = vol2 (flat 100),
    # frames 8..11 = vol3 (gradient — the last volume).
    pixels = np.zeros((n_frames, rows, cols), dtype=np.uint16)
    for frame_idx in range(n_slices):              # vol1 = 0
        pixels[frame_idx] = 0
    for frame_idx in range(n_slices, 2 * n_slices):  # vol2 = 100
        pixels[frame_idx] = 100
    for frame_idx in range(2 * n_slices, n_frames):   # vol3 = gradient
        pixels[frame_idx] = np.arange(rows * cols, dtype=np.uint16).reshape(rows, cols)

    ds.PixelData = pixels.tobytes()
    path = tmp_path / "4d.dcm"
    pydicom.dcmwrite(str(path), ds)

    result = _sample_dicom(path)
    assert result.ndim == 2
    # Last volume has a gradient → max > 0. Middle volume is flat 100 which
    # after percentile normalization would also be non-zero but with all equal
    # values → we verify the last volume by checking it normalizes to varying values.
    assert result.max() > result.min(), "Last volume (gradient) should have varying pixel values"


def test_sample_dicom_raises_on_no_pixel_data(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_dicom
    import pydicom
    import pydicom.uid
    from pydicom.dataset import FileDataset

    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    ds = FileDataset(
        str(tmp_path / "nopixels.dcm"), {}, file_meta=file_meta, preamble=b"\x00" * 128
    )
    ds.Rows = 16
    ds.Columns = 16
    pydicom.dcmwrite(str(tmp_path / "nopixels.dcm"), ds)

    with pytest.raises((ValueError, Exception)):
        _sample_dicom(tmp_path / "nopixels.dcm")


# ---------------------------------------------------------------------------
# _sample_nifti
# ---------------------------------------------------------------------------


def test_sample_nifti_3d_returns_2d_uint8(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_nifti

    nii = _make_nifti_3d(tmp_path / "vol.nii")
    result = _sample_nifti(nii)
    assert result.ndim == 2
    assert result.dtype == np.uint8


def test_sample_nifti_4d_returns_2d(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_nifti

    nii = _make_nifti_4d(tmp_path / "vol4d.nii")
    result = _sample_nifti(nii)
    assert result.ndim == 2


def test_sample_nifti_4d_uses_last_volume(tmp_path: Path) -> None:
    """For 4D volumes the LAST volume must be sampled, not the middle one."""
    import nibabel as nib
    from simpleBIDS.patterns.slice_sampler import _sample_nifti

    n_vols = 5
    shape_3d = (16, 16, 8)
    data = np.zeros((*shape_3d, n_vols), dtype=np.float32)

    # All volumes except the last are flat (uniform → normalizes to all-zeros)
    for v in range(n_vols - 1):
        data[..., v] = 100.0

    # Last volume: gradient values → normalizes to a non-trivial result
    data[..., -1] = np.arange(
        np.prod(shape_3d), dtype=np.float32
    ).reshape(shape_3d)

    nii_path = tmp_path / "4d_last_vol.nii"
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(nii_path))

    result = _sample_nifti(nii_path)
    assert result.ndim == 2
    # If the last volume was used (gradient), at least some pixels are > 0.
    # If the middle volume (index 2) were used instead, all pixels would be 0.
    assert result.max() > 0, "Expected non-zero pixels from last-volume gradient"


def test_sample_nifti_shape_has_correct_rows(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import _sample_nifti

    # Shape (X, Y, Z) → middle axial slice is (X, Y) then rot90 → (Y, X)
    nii = _make_nifti_3d(tmp_path / "vol.nii", shape=(24, 32, 10))
    result = _sample_nifti(nii)
    # After rot90, shape will be (32, 24)
    assert result.shape == (32, 24)


# ---------------------------------------------------------------------------
# sample_slice — dispatcher
# ---------------------------------------------------------------------------


def test_sample_slice_routes_dicom(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import sample_slice

    dcm = _make_dicom_with_pixels(tmp_path / "scan.dcm")
    result = sample_slice(dcm)
    assert result.ndim == 2
    assert result.dtype == np.uint8


def test_sample_slice_routes_nifti(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import sample_slice

    nii = _make_nifti_3d(tmp_path / "scan.nii")
    result = sample_slice(nii)
    assert result.ndim == 2


def test_sample_slice_routes_nifti_gz(tmp_path: Path) -> None:
    from simpleBIDS.patterns.slice_sampler import sample_slice

    nii = _make_nifti_3d(tmp_path / "scan.nii.gz")
    result = sample_slice(nii)
    assert result.ndim == 2
