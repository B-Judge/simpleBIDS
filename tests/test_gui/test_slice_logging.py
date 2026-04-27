"""Tests for slice-preview PNG logging to label_previews/ directory.

SeriesPanel saves a PNG to log_dir when one is provided.  These tests verify
the saving logic without a display by calling the PIL + numpy path directly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def _make_nifti_3d(path: Path, shape: tuple = (16, 16, 8)) -> Path:
    import nibabel as nib

    data = np.random.default_rng(7).random(shape).astype(np.float32) * 1000
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(path))
    return path


def _simulate_panel_save(rep_file: Path, log_dir: Path, slug: str) -> Path:
    """Reproduce SeriesPanel._load_image's save step without tkinter."""
    from PIL import Image
    from simpleBIDS.patterns.slice_sampler import sample_slice

    arr = sample_slice(rep_file)
    img = Image.fromarray(arr, mode="L").resize((320, 320))
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / f"{slug}.png"
    img.save(out)
    return out


def test_png_saved_to_log_dir(tmp_path: Path) -> None:
    nii = _make_nifti_3d(tmp_path / "vol.nii")
    log_dir = tmp_path / "label_previews"
    saved = _simulate_panel_save(nii, log_dir, slug="001_T1w")
    assert saved.exists(), "PNG was not written to log_dir"
    assert saved.suffix == ".png"


def test_png_filename_matches_slug(tmp_path: Path) -> None:
    nii = _make_nifti_3d(tmp_path / "vol.nii")
    log_dir = tmp_path / "label_previews"
    slug = "002_BOLD_rest"
    saved = _simulate_panel_save(nii, log_dir, slug=slug)
    assert saved.name == f"{slug}.png"


def test_log_dir_created_if_missing(tmp_path: Path) -> None:
    nii = _make_nifti_3d(tmp_path / "vol.nii")
    log_dir = tmp_path / "deep" / "nested" / "label_previews"
    assert not log_dir.exists()
    _simulate_panel_save(nii, log_dir, slug="test")
    assert log_dir.exists()


def test_png_is_readable_image(tmp_path: Path) -> None:
    from PIL import Image

    nii = _make_nifti_3d(tmp_path / "vol.nii")
    log_dir = tmp_path / "label_previews"
    saved = _simulate_panel_save(nii, log_dir, slug="check")
    img = Image.open(saved)
    assert img.size == (320, 320)
    assert img.mode == "L"


def test_second_series_adds_second_png(tmp_path: Path) -> None:
    nii1 = _make_nifti_3d(tmp_path / "a.nii")
    nii2 = _make_nifti_3d(tmp_path / "b.nii")
    log_dir = tmp_path / "label_previews"
    _simulate_panel_save(nii1, log_dir, slug="001_T1w")
    _simulate_panel_save(nii2, log_dir, slug="002_BOLD")
    pngs = list(log_dir.glob("*.png"))
    assert len(pngs) == 2
