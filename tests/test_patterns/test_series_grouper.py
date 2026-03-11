"""Tests for series_grouper — BIDS label heuristics and DICOM grouping."""

from __future__ import annotations

from pathlib import Path

import pydicom
import pydicom.uid
import pytest
from pydicom.dataset import FileDataset

from simpleBIDS.patterns.series_grouper import (
    SeriesGroup,
    _stem_without_gz,
    group_dicom_series,
    group_nifti_files,
    suggest_bids_labels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dicom(path: Path, *, series_uid: str, study_uid: str, series_number: int,
                instance_number: int, series_description: str, modality: str = "MR",
                image_type: list[str] | None = None) -> Path:
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
    ds.ImageType = image_type or ["ORIGINAL", "PRIMARY", "M"]
    ds.Rows = 64
    ds.Columns = 64
    pydicom.dcmwrite(str(path), ds)
    return path


def _make_series(root: Path, desc: str, n: int, series_number: int = 1,
                 modality: str = "MR", image_type: list[str] | None = None) -> str:
    root.mkdir(parents=True, exist_ok=True)
    uid = pydicom.uid.generate_uid()
    study_uid = pydicom.uid.generate_uid()
    for i in range(1, n + 1):
        _make_dicom(root / f"{desc}_{i:03d}.dcm", series_uid=uid, study_uid=study_uid,
                    series_number=series_number, instance_number=i,
                    series_description=desc, modality=modality, image_type=image_type)
    return uid


# ---------------------------------------------------------------------------
# suggest_bids_labels — comprehensive heuristic tests
# ---------------------------------------------------------------------------

class TestSuggestBidsLabels:
    """Each method tests one series type."""

    # --- Functional --------------------------------------------------------
    def test_bold(self):
        assert suggest_bids_labels("BOLD_rest", "MR", [], 300) == ("func", "bold")

    def test_fmri(self):
        assert suggest_bids_labels("rsfMRI", "MR", [], 200) == ("func", "bold")

    def test_sbref(self):
        assert suggest_bids_labels("BOLD_SBRef", "MR", [], 1) == ("func", "sbref")

    def test_resting_state(self):
        dt, sf = suggest_bids_labels("Resting State EPI", "MR", [], 150)
        assert dt == "func" and sf == "bold"

    # --- DWI ---------------------------------------------------------------
    def test_dwi(self):
        assert suggest_bids_labels("DWI_b1000", "MR", [], 60) == ("dwi", "dwi")

    def test_dti(self):
        dt, sf = suggest_bids_labels("DTI_30dir", "MR", [], 30)
        assert dt == "dwi" and sf == "dwi"

    def test_diffusion_image_type(self):
        dt, sf = suggest_bids_labels("ep2d_diff", "MR", ["ORIGINAL", "PRIMARY", "DIFFUSION"], 60)
        assert dt == "dwi" and sf == "dwi"

    # --- Anatomical --------------------------------------------------------
    def test_t1w_mprage(self):
        assert suggest_bids_labels("T1w_MPRAGE", "MR", [], 176) == ("anat", "T1w")

    def test_t1w_spgr(self):
        dt, sf = suggest_bids_labels("3D_T1_SPGR", "MR", [], 160)
        assert dt == "anat" and sf == "T1w"

    def test_t2w_tse(self):
        assert suggest_bids_labels("T2w_TSE", "MR", [], 30) == ("anat", "T2w")

    def test_flair(self):
        assert suggest_bids_labels("T2_FLAIR", "MR", [], 30) == ("anat", "FLAIR")

    def test_flair_beats_t2(self):
        # FLAIR should win over T2w even though "T2" appears in the description
        dt, sf = suggest_bids_labels("T2_FLAIR_3D", "MR", [], 176)
        assert sf == "FLAIR"

    def test_t2star(self):
        dt, sf = suggest_bids_labels("T2star_GRE", "MR", [], 30)
        assert dt == "anat" and sf == "T2starw"

    def test_swi(self):
        dt, sf = suggest_bids_labels("SWI_magnitude", "MR", [], 72)
        assert dt == "anat"

    def test_pdw(self):
        dt, sf = suggest_bids_labels("PDw_TSE", "MR", [], 30)
        assert dt == "anat" and sf == "PDw"

    def test_mp2rage(self):
        dt, sf = suggest_bids_labels("MP2RAGE_UNI", "MR", [], 176)
        assert dt == "anat" and sf == "MP2RAGE"

    def test_unit1(self):
        dt, sf = suggest_bids_labels("MP2RAGE_UNIT1", "MR", [], 176)
        assert dt == "anat" and sf == "UNIT1"

    def test_angio(self):
        dt, sf = suggest_bids_labels("3D_TOF_MRA", "MR", [], 120)
        assert dt == "anat" and sf == "angio"

    # --- Field maps --------------------------------------------------------
    def test_phasediff(self):
        dt, sf = suggest_bids_labels("gre_field_mapping_phasediff", "MR", [], 1)
        assert dt == "fmap"

    def test_magnitude(self):
        dt, sf = suggest_bids_labels("gre_field_mapping_magnitude1", "MR", [], 1)
        assert dt == "fmap"

    # --- Perfusion ---------------------------------------------------------
    def test_asl(self):
        dt, sf = suggest_bids_labels("pCASL_rest", "MR", [], 60)
        assert dt == "perf" and sf == "asl"

    def test_m0scan(self):
        dt, sf = suggest_bids_labels("M0_scan", "MR", [], 1)
        assert dt == "perf" and sf == "m0scan"

    # --- Non-MR modalities -------------------------------------------------
    def test_ct(self):
        assert suggest_bids_labels("HEAD CT", "CT", [], 300) == ("anat", "CT")

    def test_pet(self):
        assert suggest_bids_labels("FDG PET", "PT", [], 150) == ("pet", "pet")

    # --- Temporal heuristic ------------------------------------------------
    def test_many_volumes_fallback_bold(self):
        """Unknown description + 50+ volumes → guess func/bold."""
        dt, sf = suggest_bids_labels("ep2d_unknown_protocol", "MR", [], 200,
                                     number_of_temporal_positions=200)
        assert dt == "func" and sf == "bold"

    # --- Unknown -----------------------------------------------------------
    def test_unknown_returns_none(self):
        assert suggest_bids_labels("XYZ_unknown_sequence", "MR", [], 5) == (None, None)


# ---------------------------------------------------------------------------
# group_dicom_series
# ---------------------------------------------------------------------------

class TestGroupDicomSeries:
    def test_basic_grouping(self, tmp_path):
        _make_series(tmp_path, "T1w_MPRAGE", 120, series_number=1)
        _make_series(tmp_path, "BOLD_rest", 300, series_number=2)
        groups = group_dicom_series(tmp_path)
        assert len(groups) == 2

    def test_returns_series_group_objects(self, tmp_path):
        _make_series(tmp_path, "T1w", 5)
        groups = group_dicom_series(tmp_path)
        assert all(isinstance(g, SeriesGroup) for g in groups)

    def test_file_count(self, tmp_path):
        _make_series(tmp_path, "T1w", 176)
        groups = group_dicom_series(tmp_path)
        assert groups[0].file_count == 176

    def test_bids_suggestion_t1w(self, tmp_path):
        _make_series(tmp_path, "T1w_MPRAGE", 10)
        groups = group_dicom_series(tmp_path)
        assert groups[0].suggested_datatype == "anat"
        assert groups[0].suggested_suffix == "T1w"

    def test_bids_suggestion_bold(self, tmp_path):
        _make_series(tmp_path, "BOLD_resting_state", 200, series_number=2)
        groups = group_dicom_series(tmp_path)
        assert groups[0].suggested_datatype == "func"
        assert groups[0].suggested_suffix == "bold"

    def test_bids_suggestion_dwi_from_image_type(self, tmp_path):
        _make_series(tmp_path, "ep2d_diff_mgh_dti", 64,
                     image_type=["ORIGINAL", "PRIMARY", "DIFFUSION"])
        groups = group_dicom_series(tmp_path)
        assert groups[0].suggested_datatype == "dwi"

    def test_localizer_flagged(self, tmp_path):
        _make_series(tmp_path, "AAHead_Scout", 3,
                     image_type=["ORIGINAL", "PRIMARY", "LOCALIZER"])
        groups = group_dicom_series(tmp_path)
        assert groups[0].is_localizer is True

    def test_normal_series_not_flagged(self, tmp_path):
        _make_series(tmp_path, "T1w_MPRAGE", 5)
        groups = group_dicom_series(tmp_path)
        assert groups[0].is_localizer is False

    def test_sorted_by_series_number(self, tmp_path):
        for i in [3, 1, 2]:
            _make_series(tmp_path / f"s{i}", f"series_{i}", 3, series_number=i)
        groups = group_dicom_series(tmp_path)
        nums = [g.series_number for g in groups]
        assert nums == sorted(nums)

    def test_metadata_stored_in_extra(self, tmp_path):
        _make_series(tmp_path, "T1w", 5)
        groups = group_dicom_series(tmp_path)
        assert "dicom_metadata" in groups[0].extra

    def test_progress_callback(self, tmp_path):
        _make_series(tmp_path, "T1w", 5)
        calls = []
        group_dicom_series(tmp_path, progress_callback=lambda d, t: calls.append((d, t)))
        assert len(calls) == 5

    def test_empty_directory(self, tmp_path):
        groups = group_dicom_series(tmp_path)
        assert groups == []


# ---------------------------------------------------------------------------
# SeriesGroup.slug
# ---------------------------------------------------------------------------

class TestSeriesGroupSlug:
    def _group(self, **kw) -> SeriesGroup:
        defaults = dict(series_description=None, series_number=None, modality=None,
                        all_files=[], representative_file=Path("/x"),
                        file_count=1)
        defaults.update(kw)
        return SeriesGroup(**defaults)

    def test_slug_with_number_and_desc(self):
        g = self._group(series_number=3, series_description="T1w MPRAGE")
        assert g.slug.startswith("003_")
        assert "T1w" in g.slug

    def test_slug_no_special_chars(self):
        g = self._group(series_number=1, series_description="T2 FLAIR / special!")
        assert all(c.isalnum() or c == "_" for c in g.slug)

    def test_slug_unknown_fallback(self):
        g = self._group()
        assert g.slug == "unknown"

    def test_slug_max_length(self):
        g = self._group(series_number=1, series_description="A" * 100)
        # Description part capped at 48 chars
        assert len(g.slug) <= 4 + 48  # "001_" + 48


# ---------------------------------------------------------------------------
# _stem_without_gz
# ---------------------------------------------------------------------------

def test_stem_without_gz():
    assert _stem_without_gz(Path("sub-01_T1w.nii.gz")) == "sub-01_T1w"

def test_stem_without_gz_plain_nii():
    assert _stem_without_gz(Path("bold.nii")) == "bold"

def test_stem_without_gz_other():
    assert _stem_without_gz(Path("file.txt")) == "file"
