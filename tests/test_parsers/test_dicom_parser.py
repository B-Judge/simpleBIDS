"""Tests for dicom_parser — uses pydicom built-in test files and synthetic DICOMs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pydicom
import pydicom.uid
import pytest
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset, FileDataset
from pydicom.sequence import Sequence

from simpleBIDS.parsers.dicom_parser import (
    DicomMetadata,
    DicomSeries,
    _is_localizer_raw,
    _safe_int,
    parse_dicom_file,
    parse_dicom_series,
    scan_dicom_directory,
    walk_dicom_directory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ct_file() -> Path:
    return Path(get_testdata_file("CT_small.dcm"))


@pytest.fixture
def mr_file() -> Path:
    return Path(get_testdata_file("MR_small.dcm"))


def _make_dicom(
    path: Path,
    *,
    series_uid: str | None = None,
    study_uid: str | None = None,
    series_number: int = 1,
    instance_number: int = 1,
    series_description: str = "TestSeries",
    modality: str = "MR",
    image_type: list[str] | None = None,
    echo_time: float | None = None,
    repetition_time: float | None = None,
    rows: int = 64,
    columns: int = 64,
) -> Path:
    """Write a minimal valid DICOM file to *path*."""
    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.UID("1.2.840.10008.5.1.4.1.1.4")
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_implicit_VR = False
    ds.is_little_endian = True

    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or pydicom.uid.generate_uid()
    ds.SeriesInstanceUID = series_uid or pydicom.uid.generate_uid()
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    ds.SeriesDescription = series_description
    ds.Modality = modality
    ds.ImageType = image_type or ["ORIGINAL", "PRIMARY", "M"]
    ds.Rows = rows
    ds.Columns = columns
    if echo_time is not None:
        ds.EchoTime = echo_time
    if repetition_time is not None:
        ds.RepetitionTime = repetition_time

    pydicom.dcmwrite(str(path), ds)
    return path


# ---------------------------------------------------------------------------
# parse_dicom_file
# ---------------------------------------------------------------------------

class TestParseDicomFile:
    def test_returns_metadata_type(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert isinstance(meta, DicomMetadata)

    def test_ct_modality(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert meta.modality == "CT"

    def test_mr_modality(self, mr_file):
        meta = parse_dicom_file(mr_file)
        assert meta.modality == "MR"

    def test_file_count_is_one(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert meta.file_count == 1

    def test_representative_file_set(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert meta.representative_file == ct_file

    def test_geometry_populated(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert meta.rows is not None and meta.rows > 0
        assert meta.columns is not None and meta.columns > 0

    def test_instance_number(self, ct_file):
        meta = parse_dicom_file(ct_file)
        assert meta.instance_number is not None

    def test_synthetic_echo_time(self, tmp_path):
        p = _make_dicom(tmp_path / "slice.dcm", echo_time=30.0, repetition_time=2000.0)
        meta = parse_dicom_file(p)
        assert meta.echo_time == pytest.approx(30.0)
        assert meta.repetition_time == pytest.approx(2000.0)

    def test_synthetic_image_type(self, tmp_path):
        p = _make_dicom(tmp_path / "s.dcm", image_type=["ORIGINAL", "PRIMARY", "DIFFUSION"])
        meta = parse_dicom_file(p)
        assert "DIFFUSION" in meta.image_type

    def test_raises_on_non_dicom(self, tmp_path):
        bad = tmp_path / "notadicom.dcm"
        bad.write_bytes(b"this is not dicom")
        with pytest.raises(Exception):
            parse_dicom_file(bad)

    def test_localizer_flag_from_image_type(self, tmp_path):
        p = _make_dicom(tmp_path / "loc.dcm", image_type=["ORIGINAL", "PRIMARY", "LOCALIZER"])
        meta = parse_dicom_file(p)
        assert meta.is_localizer is True

    def test_localizer_flag_from_description(self, tmp_path):
        p = _make_dicom(tmp_path / "scout.dcm", series_description="AAHead_Scout")
        meta = parse_dicom_file(p)
        assert meta.is_localizer is True

    def test_normal_series_not_localizer(self, tmp_path):
        p = _make_dicom(tmp_path / "t1.dcm", series_description="T1w_MPRAGE")
        meta = parse_dicom_file(p)
        assert meta.is_localizer is False

    def test_series_instance_uid_populated(self, tmp_path):
        uid = pydicom.uid.generate_uid()
        p = _make_dicom(tmp_path / "s.dcm", series_uid=uid)
        meta = parse_dicom_file(p)
        assert meta.series_instance_uid == uid


# ---------------------------------------------------------------------------
# parse_dicom_series
# ---------------------------------------------------------------------------

class TestParseDicomSeries:
    def test_file_count_reflects_collection(self, tmp_path):
        uid = pydicom.uid.generate_uid()
        files = [
            _make_dicom(tmp_path / f"s{i}.dcm", series_uid=uid, instance_number=i)
            for i in range(1, 6)
        ]
        meta = parse_dicom_series(files)
        assert meta.file_count == 5

    def test_representative_is_middle(self, tmp_path):
        uid = pydicom.uid.generate_uid()
        files = sorted([
            _make_dicom(tmp_path / f"s{i:02d}.dcm", series_uid=uid, instance_number=i)
            for i in range(1, 8)
        ])
        meta = parse_dicom_series(files)
        # Middle of 7 sorted files is index 3 (0-based)
        assert meta.representative_file == files[3]

    def test_raises_on_empty_list(self):
        with pytest.raises(ValueError):
            parse_dicom_series([])


# ---------------------------------------------------------------------------
# scan_dicom_directory
# ---------------------------------------------------------------------------

class TestScanDicomDirectory:
    def _make_series(
        self, tmp_path: Path, desc: str, n_slices: int, series_number: int = 1
    ) -> str:
        """Create *n_slices* DICOM files for one series. Returns the series UID."""
        tmp_path.mkdir(parents=True, exist_ok=True)
        uid = pydicom.uid.generate_uid()
        study_uid = pydicom.uid.generate_uid()
        for i in range(1, n_slices + 1):
            _make_dicom(
                tmp_path / f"{desc}_{i:03d}.dcm",
                series_uid=uid,
                study_uid=study_uid,
                series_number=series_number,
                instance_number=i,
                series_description=desc,
            )
        return uid

    def test_finds_correct_number_of_series(self, tmp_path):
        self._make_series(tmp_path, "T1w_MPRAGE", 120, series_number=1)
        self._make_series(tmp_path, "BOLD_rest", 300, series_number=2)
        series = scan_dicom_directory(tmp_path)
        assert len(series) == 2

    def test_returns_dicom_series_objects(self, tmp_path):
        self._make_series(tmp_path, "T1w", 5)
        series = scan_dicom_directory(tmp_path)
        assert all(isinstance(s, DicomSeries) for s in series)

    def test_file_count_correct(self, tmp_path):
        self._make_series(tmp_path, "T1w", 10)
        series = scan_dicom_directory(tmp_path)
        assert series[0].metadata.file_count == 10

    def test_files_sorted_by_instance_number(self, tmp_path):
        uid = pydicom.uid.generate_uid()
        study_uid = pydicom.uid.generate_uid()
        # Write in reverse order on disk (filenames don't match instance order)
        for i in range(10, 0, -1):
            _make_dicom(
                tmp_path / f"slice_{10 - i:02d}.dcm",
                series_uid=uid,
                study_uid=study_uid,
                instance_number=i,
                series_description="T1w",
            )
        series = scan_dicom_directory(tmp_path)
        inst_numbers = []
        for f in series[0].all_files:
            ds = pydicom.dcmread(str(f), specific_tags=["InstanceNumber"],
                                 stop_before_pixels=True)
            inst_numbers.append(int(ds.InstanceNumber))
        assert inst_numbers == sorted(inst_numbers)

    def test_non_dicom_files_skipped(self, tmp_path):
        self._make_series(tmp_path, "T1w", 3)
        (tmp_path / "README.txt").write_text("not a dicom")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        series = scan_dicom_directory(tmp_path)
        assert len(series) == 1
        assert series[0].metadata.file_count == 3

    def test_subdirectory_recursion(self, tmp_path):
        subdir = tmp_path / "subject01" / "session1"
        subdir.mkdir(parents=True)
        self._make_series(subdir, "T1w", 5)
        series = scan_dicom_directory(tmp_path)
        assert len(series) == 1

    def test_progress_callback_called(self, tmp_path):
        self._make_series(tmp_path, "T1w", 5)
        calls: list[tuple[int, int]] = []
        scan_dicom_directory(tmp_path, progress_callback=lambda d, t: calls.append((d, t)))
        assert len(calls) == 5
        assert calls[-1] == (5, 5)

    def test_empty_directory(self, tmp_path):
        series = scan_dicom_directory(tmp_path)
        assert series == []

    def test_sorted_by_series_number(self, tmp_path):
        self._make_series(tmp_path / "a", "BOLD_rest", 3, series_number=3)
        self._make_series(tmp_path / "b", "T1w_MPRAGE", 3, series_number=1)
        self._make_series(tmp_path / "c", "DWI", 3, series_number=2)
        series = scan_dicom_directory(tmp_path)
        nums = [s.metadata.series_number for s in series]
        assert nums == sorted(nums)

    def test_same_desc_same_study_merged(self, tmp_path):
        """Multiple runs with the same description in one study → 1 merged group."""
        uid1 = pydicom.uid.generate_uid()
        uid2 = pydicom.uid.generate_uid()
        study_uid = pydicom.uid.generate_uid()
        for i in range(1, 4):
            _make_dicom(tmp_path / f"s1_{i}.dcm", series_uid=uid1, study_uid=study_uid,
                        series_number=1, series_description="BOLD_rest", instance_number=i)
            _make_dicom(tmp_path / f"s2_{i}.dcm", series_uid=uid2, study_uid=study_uid,
                        series_number=2, series_description="BOLD_rest", instance_number=i)
        series = scan_dicom_directory(tmp_path)
        # Same study + same description → one merged group with all 6 files
        assert len(series) == 1
        assert series[0].metadata.file_count == 6

    def test_same_desc_different_study_separate(self, tmp_path):
        """Same description but different studies (patients) → 2 separate groups."""
        study_uid_a = pydicom.uid.generate_uid()
        study_uid_b = pydicom.uid.generate_uid()
        _make_dicom(tmp_path / "a.dcm", study_uid=study_uid_a, series_description="T1w")
        _make_dicom(tmp_path / "b.dcm", study_uid=study_uid_b, series_description="T1w")
        series = scan_dicom_directory(tmp_path)
        assert len(series) == 2


# ---------------------------------------------------------------------------
# walk_dicom_directory (compatibility wrapper)
# ---------------------------------------------------------------------------

def test_walk_dicom_directory_returns_dict(tmp_path):
    uid = pydicom.uid.generate_uid()
    study_uid = pydicom.uid.generate_uid()  # shared study so files merge into one group
    for i in range(1, 4):
        _make_dicom(tmp_path / f"s{i}.dcm", series_uid=uid, study_uid=study_uid,
                    series_description="T1w", series_number=1, instance_number=i)
    result = walk_dicom_directory(tmp_path)
    assert isinstance(result, dict)
    assert len(result) == 1
    key = list(result.keys())[0]
    assert key == ("T1w", 1)
    assert len(result[key]) == 3


# ---------------------------------------------------------------------------
# PET tracer grouping
# ---------------------------------------------------------------------------


def _make_pet_dicom(
    path: Path,
    *,
    study_uid: str,
    series_description: str = "PET_WB",
    radiopharmaceutical: str = "FDG",
    instance_number: int = 1,
) -> Path:
    """Write a minimal PET DICOM with a RadiopharmaceuticalInformationSequence."""
    import pydicom.uid
    from pydicom.dataset import FileDataset, Dataset
    from pydicom.sequence import Sequence

    file_meta = pydicom.dataset.FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.128"
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = pydicom.uid.generate_uid()
    ds.SeriesNumber = 1
    ds.InstanceNumber = instance_number
    ds.SeriesDescription = series_description
    ds.Modality = "PT"
    ds.Rows = 16
    ds.Columns = 16

    radio_item = Dataset()
    radio_item.Radiopharmaceutical = radiopharmaceutical
    ds.RadiopharmaceuticalInformationSequence = Sequence([radio_item])

    pydicom.dcmwrite(str(path), ds)
    return path


def test_pet_same_tracer_same_study_merged(tmp_path):
    """PET frames with the same tracer and study are merged into one group."""
    study_uid = pydicom.uid.generate_uid()
    _make_pet_dicom(tmp_path / "a.dcm", study_uid=study_uid, radiopharmaceutical="FDG", instance_number=1)
    _make_pet_dicom(tmp_path / "b.dcm", study_uid=study_uid, radiopharmaceutical="FDG", instance_number=2)
    series = scan_dicom_directory(tmp_path)
    assert len(series) == 1
    assert series[0].metadata.file_count == 2


def test_pet_different_tracer_same_study_separate(tmp_path):
    """PET with different tracers in one study → separate groups."""
    study_uid = pydicom.uid.generate_uid()
    _make_pet_dicom(tmp_path / "fdg.dcm", study_uid=study_uid, radiopharmaceutical="FDG")
    _make_pet_dicom(tmp_path / "psma.dcm", study_uid=study_uid, radiopharmaceutical="PSMA-11")
    series = scan_dicom_directory(tmp_path)
    assert len(series) == 2


# ---------------------------------------------------------------------------
# 4D DICOM — last temporal position as representative
# ---------------------------------------------------------------------------


def _make_4d_dicom_series(
    tmp_path: Path,
    n_vols: int,
    n_slices: int,
    study_uid: str,
    series_description: str = "BOLD_rest",
) -> list[Path]:
    """Write n_vols × n_slices DICOM files with TemporalPositionIdentifier set."""
    files = []
    inst = 1
    for vol in range(1, n_vols + 1):
        for slc in range(1, n_slices + 1):
            path = tmp_path / f"vol{vol:03d}_slc{slc:03d}.dcm"
            file_meta = pydicom.dataset.FileMetaDataset()
            file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
            file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
            file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            from pydicom.dataset import FileDataset
            ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
            ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
            ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = pydicom.uid.generate_uid()
            ds.SeriesNumber = 1
            ds.InstanceNumber = inst
            ds.TemporalPositionIdentifier = vol
            ds.SeriesDescription = series_description
            ds.Modality = "MR"
            ds.Rows = 16
            ds.Columns = 16
            pydicom.dcmwrite(str(path), ds)
            files.append(path)
            inst += 1
    return files


def test_4d_representative_is_from_last_volume(tmp_path):
    """The representative file chosen for display must come from the last volume."""
    study_uid = pydicom.uid.generate_uid()
    n_vols, n_slices = 5, 4
    _make_4d_dicom_series(tmp_path, n_vols=n_vols, n_slices=n_slices, study_uid=study_uid)

    series = scan_dicom_directory(tmp_path)
    assert len(series) == 1

    rep = series[0].metadata.representative_file
    ds = pydicom.dcmread(str(rep), specific_tags=["TemporalPositionIdentifier"],
                         stop_before_pixels=True)
    tp = int(ds.TemporalPositionIdentifier)
    assert tp == n_vols, f"Expected representative from vol {n_vols}, got vol {tp}"


def test_3d_series_representative_is_middle_file(tmp_path):
    """A 3D series (no TemporalPositionIdentifier) keeps the middle-file representative."""
    study_uid = pydicom.uid.generate_uid()
    n_slices = 9
    for slc in range(1, n_slices + 1):
        _make_dicom(tmp_path / f"slc{slc:03d}.dcm", study_uid=study_uid,
                    instance_number=slc, series_description="T1w")
    series = scan_dicom_directory(tmp_path)
    assert len(series) == 1
    # All files default to temporal_pos=1, so representative is middle spatial slice
    all_files = series[0].all_files
    assert series[0].metadata.representative_file == all_files[len(all_files) // 2]


# ---------------------------------------------------------------------------
# _is_localizer_raw
# ---------------------------------------------------------------------------

class TestIsLocalizerRaw:
    def test_localizer_in_image_type(self):
        assert _is_localizer_raw(["ORIGINAL", "PRIMARY", "LOCALIZER"], None)

    def test_scout_in_description(self):
        assert _is_localizer_raw([], "AAHead_Scout")

    def test_localizer_in_description(self):
        assert _is_localizer_raw([], "3-Plane Localizer")

    def test_normal_series_false(self):
        assert not _is_localizer_raw(["ORIGINAL", "PRIMARY", "M"], "T1w_MPRAGE")


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

def test_safe_int_numeric():
    assert _safe_int("5") == 5

def test_safe_int_float_string():
    assert _safe_int("3.0") == 3

def test_safe_int_none():
    assert _safe_int(None) is None

def test_safe_int_invalid():
    assert _safe_int("abc") is None
