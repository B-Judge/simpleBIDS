"""Tests for bids/config_builder.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simpleBIDS.bids.config_builder import LabeledSeries, build_config, write_config, _build_criteria
from simpleBIDS.patterns.series_grouper import SeriesGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_group(
    tmp_path: Path,
    *,
    desc: str = "T1w_MPRAGE",
    series_number: int = 1,
    extra: dict | None = None,
) -> SeriesGroup:
    return SeriesGroup(
        series_description=desc,
        series_number=series_number,
        modality="MR",
        all_files=[],
        representative_file=tmp_path / "x.dcm",
        file_count=5,
        extra=extra or {},
    )


def _make_labeled(
    tmp_path: Path,
    *,
    datatype: str = "anat",
    suffix: str = "T1w",
    entities: dict | None = None,
    custom_criteria: dict | None = None,
    exclude: bool = False,
    desc: str = "T1w_MPRAGE",
    series_number: int = 1,
) -> LabeledSeries:
    return LabeledSeries(
        series_group=_make_group(tmp_path, desc=desc, series_number=series_number),
        datatype=datatype,
        suffix=suffix,
        entities=entities or {},
        custom_criteria=custom_criteria or {},
        exclude=exclude,
    )


# ---------------------------------------------------------------------------
# build_config
# ---------------------------------------------------------------------------


def test_build_config_basic_structure(tmp_path: Path) -> None:
    ls = _make_labeled(tmp_path)
    config = build_config([ls])
    assert "descriptions" in config
    assert len(config["descriptions"]) == 1
    assert config["descriptions"][0]["datatype"] == "anat"
    assert config["descriptions"][0]["suffix"] == "T1w"


def test_build_config_multiple_series(tmp_path: Path) -> None:
    labeled = [
        _make_labeled(tmp_path, datatype="anat", suffix="T1w", desc="T1w"),
        _make_labeled(tmp_path, datatype="func", suffix="bold", desc="BOLD"),
        _make_labeled(tmp_path, datatype="dwi", suffix="dwi", desc="DWI"),
    ]
    config = build_config(labeled)
    assert len(config["descriptions"]) == 3


def test_build_config_exclude_omits_series(tmp_path: Path) -> None:
    labeled = [
        _make_labeled(tmp_path, datatype="anat", suffix="T1w", exclude=False),
        _make_labeled(tmp_path, datatype="anat", suffix="T2w", desc="T2w", exclude=True),
    ]
    config = build_config(labeled)
    # Only the non-excluded series should appear
    assert len(config["descriptions"]) == 1
    assert config["descriptions"][0]["suffix"] == "T1w"


def test_build_config_entities_added_as_custom_entities(tmp_path: Path) -> None:
    ls = _make_labeled(
        tmp_path, datatype="func", suffix="bold", entities={"task": "rest", "run": "01"}
    )
    config = build_config([ls])
    desc = config["descriptions"][0]
    assert "custom_entities" in desc
    assert desc["custom_entities"]["task"] == "rest"
    assert desc["custom_entities"]["run"] == "01"


def test_build_config_no_entities_no_custom_entities_key(tmp_path: Path) -> None:
    ls = _make_labeled(tmp_path, entities={})
    config = build_config([ls])
    assert "custom_entities" not in config["descriptions"][0]


def test_build_config_empty_list(tmp_path: Path) -> None:
    config = build_config([])
    assert config["descriptions"] == []


def test_build_config_all_excluded(tmp_path: Path) -> None:
    labeled = [_make_labeled(tmp_path, exclude=True)]
    config = build_config(labeled)
    assert config["descriptions"] == []


# ---------------------------------------------------------------------------
# _build_criteria
# ---------------------------------------------------------------------------


def test_build_criteria_series_description(tmp_path: Path) -> None:
    ls = _make_labeled(tmp_path, desc="T1w_MPRAGE")
    criteria = _build_criteria(ls)
    assert criteria["SeriesDescription"] == "T1w_MPRAGE"


def test_build_criteria_series_number(tmp_path: Path) -> None:
    ls = _make_labeled(tmp_path, series_number=3)
    criteria = _build_criteria(ls)
    assert criteria["SeriesNumber"] == 3


def test_build_criteria_no_series_number_when_none(tmp_path: Path) -> None:
    group = SeriesGroup(
        series_description="T1w",
        series_number=None,  # explicitly None
        modality="MR",
        all_files=[],
        representative_file=tmp_path / "x.dcm",
        file_count=1,
    )
    ls = LabeledSeries(series_group=group, datatype="anat", suffix="T1w")
    criteria = _build_criteria(ls)
    assert "SeriesNumber" not in criteria


def test_build_criteria_image_type_from_dicom_metadata(tmp_path: Path) -> None:
    from simpleBIDS.parsers.dicom_parser import DicomMetadata
    dicom_meta = DicomMetadata(
        representative_file=tmp_path / "x.dcm",
        file_count=5,
        image_type=["ORIGINAL", "PRIMARY", "M"],
    )
    group = _make_group(tmp_path, extra={"dicom_metadata": dicom_meta})
    ls = LabeledSeries(series_group=group, datatype="anat", suffix="T1w")
    criteria = _build_criteria(ls)
    assert "ImageType" in criteria
    assert criteria["ImageType"] == ["ORIGINAL", "PRIMARY", "M"]


def test_build_criteria_no_image_type_when_empty(tmp_path: Path) -> None:
    from simpleBIDS.parsers.dicom_parser import DicomMetadata
    dicom_meta = DicomMetadata(
        representative_file=tmp_path / "x.dcm",
        file_count=5,
        image_type=[],
    )
    group = _make_group(tmp_path, extra={"dicom_metadata": dicom_meta})
    ls = LabeledSeries(series_group=group, datatype="anat", suffix="T1w")
    criteria = _build_criteria(ls)
    assert "ImageType" not in criteria


def test_build_criteria_custom_criteria_merged(tmp_path: Path) -> None:
    ls = _make_labeled(tmp_path, custom_criteria={"EchoNumber": "1"})
    criteria = _build_criteria(ls)
    assert criteria["EchoNumber"] == "1"


# ---------------------------------------------------------------------------
# write_config
# ---------------------------------------------------------------------------


def test_write_config_creates_json_file(tmp_path: Path) -> None:
    config = {"descriptions": [{"datatype": "anat", "suffix": "T1w", "criteria": {}}]}
    path = tmp_path / "code" / "dcm2bids_config.json"
    write_config(config, path)
    assert path.exists()


def test_write_config_creates_parent_dirs(tmp_path: Path) -> None:
    config = {"descriptions": []}
    path = tmp_path / "deep" / "nested" / "config.json"
    write_config(config, path)
    assert path.exists()


def test_write_config_roundtrip(tmp_path: Path) -> None:
    original = {"descriptions": [{"datatype": "func", "suffix": "bold", "criteria": {}}]}
    path = tmp_path / "config.json"
    write_config(original, path)
    loaded = json.loads(path.read_text())
    assert loaded == original


def test_write_config_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"old": true}')
    write_config({"descriptions": []}, path)
    loaded = json.loads(path.read_text())
    assert "old" not in loaded
