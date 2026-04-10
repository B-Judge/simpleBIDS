"""Tests for nifti_parser (uses synthetic NIfTI data)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


def _make_nifti(path: Path, shape=(64, 64, 30), tr: float | None = None) -> Path:
    import nibabel as nib

    data = np.zeros(shape, dtype=np.int16)
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    if tr is not None:
        img.header.set_zooms((*img.header.get_zooms()[:3], tr))
    nib.save(img, str(path))
    return path


def test_parse_nifti_basic(tmp_path):
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    nii = _make_nifti(tmp_path / "test.nii")
    meta = parse_nifti(nii)
    assert meta.shape == (64, 64, 30)
    assert len(meta.voxel_size) == 3


def test_parse_nifti_with_sidecar(tmp_path):
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    nii = _make_nifti(tmp_path / "test.nii")
    sidecar = tmp_path / "test.json"
    sidecar.write_text(json.dumps({"RepetitionTime": 2.0, "TaskName": "rest"}))
    meta = parse_nifti(nii)
    assert meta.tr == 2.0
    assert meta.task_name == "rest"


def test_parse_nifti_missing_sidecar(tmp_path):
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    nii = _make_nifti(tmp_path / "nosidecar.nii")
    meta = parse_nifti(nii)
    assert meta.sidecar == {}


def test_parse_nifti_4d_tr_from_header(tmp_path):
    """TR from the 4th zoom dimension is parsed (line 50)."""
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    nii = _make_nifti(tmp_path / "4d.nii", shape=(32, 32, 20, 10), tr=2.0)
    meta = parse_nifti(nii)
    assert meta.tr == pytest.approx(2.0)


def test_parse_nifti_raises_on_invalid_file(tmp_path):
    """parse_nifti raises (and logs) when nibabel cannot load the file (lines 38-40)."""
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    bad = tmp_path / "bad.nii"
    bad.write_bytes(b"this is not a nifti file")
    with pytest.raises(Exception):
        parse_nifti(bad)


def test_load_sidecar_malformed_json_returns_empty(tmp_path):
    """Malformed JSON sidecar is silently skipped — returns empty dict."""
    from simpleBIDS.parsers.nifti_parser import parse_nifti

    nii = _make_nifti(tmp_path / "test.nii")
    sidecar = tmp_path / "test.json"
    sidecar.write_text("{ invalid json !!!", encoding="utf-8")
    meta = parse_nifti(nii)
    assert meta.sidecar == {}


def test_walk_nifti_directory(tmp_path):
    """walk_nifti_directory finds .nii and .nii.gz files."""
    from simpleBIDS.parsers.nifti_parser import walk_nifti_directory

    _make_nifti(tmp_path / "a.nii")
    _make_nifti(tmp_path / "b.nii", shape=(16, 16, 5))
    results = walk_nifti_directory(tmp_path)
    assert len(results) == 2
    assert all(p.suffix in {".nii", ".gz"} for p in results)


def test_walk_nifti_directory_empty(tmp_path):
    """Empty directory returns empty list."""
    from simpleBIDS.parsers.nifti_parser import walk_nifti_directory

    results = walk_nifti_directory(tmp_path)
    assert results == []
