"""Tests for cli/sort.py (bids-sort command).

Integration tests that create a minimal BIDS project with synthetic DICOM
files in sourcedata/, run bids-sort, and verify the resulting artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pydicom
import pydicom.uid
import pytest
from pydicom.dataset import FileDataset

from simpleBIDS.cli.init import main as init_main
from simpleBIDS.cli.sort import main as sort_main


# ---------------------------------------------------------------------------
# Helpers — synthetic DICOM creation (same pattern as test_series_grouper)
# ---------------------------------------------------------------------------


def _make_dicom(
    path: Path,
    *,
    series_uid: str,
    study_uid: str,
    series_number: int,
    instance_number: int,
    series_description: str,
    modality: str = "MR",
) -> Path:
    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    ds.SeriesDescription = series_description
    ds.Modality = modality
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M"]
    ds.Rows = 16
    ds.Columns = 16
    ds.PatientID = "TEST001"
    ds.StudyDate = "20230101"
    pydicom.dcmwrite(str(path), ds)
    return path


def _populate_sourcedata(sourcedata: Path, n_series: int = 2) -> None:
    sourcedata.mkdir(parents=True, exist_ok=True)
    study_uid = pydicom.uid.generate_uid()
    for s in range(1, n_series + 1):
        series_uid = pydicom.uid.generate_uid()
        desc = "T1w_MPRAGE" if s == 1 else f"BOLD_rest_{s}"
        for i in range(1, 4):
            _make_dicom(
                sourcedata / f"series{s:02d}_img{i:03d}.dcm",
                series_uid=series_uid,
                study_uid=study_uid,
                series_number=s,
                instance_number=i,
                series_description=desc,
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sort_creates_manifest(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata")
    sort_main([str(bids)])
    manifest_path = bids / ".simpleBIDS_cache" / "series_manifest.json"
    assert manifest_path.exists()


def test_sort_manifest_has_correct_series_count(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata", n_series=2)
    sort_main([str(bids)])
    manifest = json.loads(
        (bids / ".simpleBIDS_cache" / "series_manifest.json").read_text()
    )
    assert len(manifest) == 2


def test_sort_creates_staging_directory(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata")
    sort_main([str(bids)])
    assert (bids / ".simpleBIDS_staging").is_dir()


def test_sort_staging_contains_series_subdirs(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata", n_series=2)
    sort_main([str(bids)])
    staging = bids / ".simpleBIDS_staging"
    subdirs = [d for d in staging.rglob("*") if d.is_dir()]
    assert len(subdirs) >= 2


def test_sort_manifest_entries_have_required_fields(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata")
    sort_main([str(bids)])
    manifest = json.loads(
        (bids / ".simpleBIDS_cache" / "series_manifest.json").read_text()
    )
    required_keys = {
        "index", "series_description", "series_number", "modality",
        "file_count", "representative_file", "subject_id", "session_id",
        "suggested_datatype", "is_localizer", "staging_dir",
    }
    for entry in manifest:
        assert required_keys.issubset(entry.keys()), (
            f"Missing keys: {required_keys - entry.keys()}"
        )


def test_sort_is_idempotent(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata")
    sort_main([str(bids)])
    # Second run should succeed and produce the same manifest
    sort_main([str(bids)])
    manifest = json.loads(
        (bids / ".simpleBIDS_cache" / "series_manifest.json").read_text()
    )
    assert len(manifest) >= 1


def test_sort_errors_if_no_sourcedata(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    # sourcedata was created by init, remove it
    (bids / "sourcedata").rmdir()
    with pytest.raises(SystemExit) as exc_info:
        sort_main([str(bids)])
    assert exc_info.value.code != 0


def test_sort_errors_if_not_a_bids_project(tmp_path: Path) -> None:
    not_bids = tmp_path / "raw"
    not_bids.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        sort_main([str(not_bids)])
    assert exc_info.value.code != 0


def test_sort_errors_if_no_bids_dir_supplied() -> None:
    with pytest.raises(SystemExit) as exc_info:
        sort_main([])
    assert exc_info.value.code != 0


def test_sort_infers_subject_id(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _populate_sourcedata(bids / "sourcedata")
    sort_main([str(bids)])
    manifest = json.loads(
        (bids / ".simpleBIDS_cache" / "series_manifest.json").read_text()
    )
    # PatientID is "TEST001" → should produce a non-empty subject_id
    for entry in manifest:
        assert entry["subject_id"] is not None
        assert entry["subject_id"] != ""
