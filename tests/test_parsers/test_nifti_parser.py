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
