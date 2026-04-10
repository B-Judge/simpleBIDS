"""Tests for cli/label.py (bids-label command, headless mode only).

GUI mode requires a live display and is not tested here.  The --headless flag
exercises the full label pipeline without tkinter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simpleBIDS.cli.init import main as init_main
from simpleBIDS.cli.label import main as label_main, _group_from_entry, _auto_label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(bids_root: Path, entries: list[dict] | None = None) -> Path:
    """Write a series_manifest.json to .simpleBIDS_cache/ and return its path."""
    if entries is None:
        entries = [
            {
                "index": 0,
                "series_description": "T1w_MPRAGE",
                "series_number": 1,
                "modality": "MR",
                "file_count": 176,
                "representative_file": str(bids_root / "sourcedata" / "placeholder.dcm"),
                "all_files": [],
                "subject_id": "001",
                "session_id": "20230101",
                "suggested_datatype": "anat",
                "suggested_suffix": "T1w",
                "is_localizer": False,
                "staging_dir": str(
                    bids_root / ".simpleBIDS_staging"
                    / "TEST001_20230101_001_T1w_MPRAGE"
                ),
                "slug": "001_T1w_MPRAGE",
                "slice_png": None,
            }
        ]
    cache = bids_root / ".simpleBIDS_cache"
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "series_manifest.json"
    manifest_path.write_text(json.dumps(entries), encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# Headless labeling — produces config
# ---------------------------------------------------------------------------


def test_headless_creates_config(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _write_manifest(bids)
    label_main([str(bids), "--headless"])
    assert (bids / "code" / "dcm2bids_config.json").exists()


def test_headless_config_has_descriptions(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _write_manifest(bids)
    label_main([str(bids), "--headless"])
    config = json.loads((bids / "code" / "dcm2bids_config.json").read_text())
    assert "descriptions" in config
    assert len(config["descriptions"]) >= 1


def test_headless_uses_suggested_labels(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _write_manifest(bids)
    label_main([str(bids), "--headless"])
    config = json.loads((bids / "code" / "dcm2bids_config.json").read_text())
    desc = config["descriptions"][0]
    assert desc["datatype"] == "anat"
    assert desc["suffix"] == "T1w"


def test_headless_multiple_series(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    entries = [
        {
            "index": i,
            "series_description": desc,
            "series_number": i + 1,
            "modality": "MR",
            "file_count": 10,
            "representative_file": str(bids / "sourcedata" / "x.dcm"),
            "all_files": [],
            "subject_id": "001",
            "session_id": "20230101",
            "suggested_datatype": dt,
            "suggested_suffix": sf,
            "is_localizer": False,
            "staging_dir": None,
            "slug": f"{i+1:03d}_{desc}",
            "slice_png": None,
        }
        for i, (desc, dt, sf) in enumerate([
            ("T1w_MPRAGE", "anat", "T1w"),
            ("BOLD_rest", "func", "bold"),
            ("DWI_b1000", "dwi", "dwi"),
        ])
    ]
    _write_manifest(bids, entries)
    label_main([str(bids), "--headless"])
    config = json.loads((bids / "code" / "dcm2bids_config.json").read_text())
    assert len(config["descriptions"]) == 3


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_label_errors_if_no_manifest(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    # No manifest written
    with pytest.raises(SystemExit) as exc_info:
        label_main([str(bids), "--headless"])
    assert exc_info.value.code != 0


def test_label_errors_if_bids_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        label_main([str(tmp_path / "nonexistent"), "--headless"])
    assert exc_info.value.code != 0


def test_label_errors_if_no_bids_dir_supplied() -> None:
    with pytest.raises(SystemExit) as exc_info:
        label_main([])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# _group_from_entry
# ---------------------------------------------------------------------------


def test_group_from_entry_basic(tmp_path: Path) -> None:
    entry = {
        "series_description": "T1w",
        "series_number": 1,
        "modality": "MR",
        "file_count": 10,
        "representative_file": str(tmp_path / "img.dcm"),
        "all_files": [],
        "subject_id": "001",
        "session_id": "20230101",
        "suggested_datatype": "anat",
        "suggested_suffix": "T1w",
        "is_localizer": False,
        "staging_dir": None,
    }
    group = _group_from_entry(entry)
    assert group.series_description == "T1w"
    assert group.subject_id == "001"
    assert group.suggested_datatype == "anat"


def test_group_from_entry_missing_optional_fields(tmp_path: Path) -> None:
    entry = {
        "series_description": None,
        "series_number": None,
        "modality": None,
        "file_count": 0,
        "representative_file": str(tmp_path / "img.dcm"),
        "all_files": [],
        "subject_id": None,
        "session_id": None,
        "suggested_datatype": None,
        "suggested_suffix": None,
        "is_localizer": False,
        "staging_dir": None,
    }
    group = _group_from_entry(entry)
    assert group.subject_id is None
    assert group.is_localizer is False


# ---------------------------------------------------------------------------
# _auto_label
# ---------------------------------------------------------------------------


def test_auto_label_uses_suggested(tmp_path: Path) -> None:
    from simpleBIDS.patterns.series_grouper import SeriesGroup
    group = SeriesGroup(
        series_description="T1w_MPRAGE",
        series_number=1,
        modality="MR",
        all_files=[],
        representative_file=tmp_path / "x.dcm",
        file_count=5,
        suggested_datatype="anat",
        suggested_suffix="T1w",
    )
    labeled = _auto_label([group], [])
    assert len(labeled) == 1
    assert labeled[0].datatype == "anat"
    assert labeled[0].suffix == "T1w"


def test_auto_label_fallback_when_no_suggestion(tmp_path: Path) -> None:
    from simpleBIDS.patterns.series_grouper import SeriesGroup
    group = SeriesGroup(
        series_description="Unknown_Protocol",
        series_number=1,
        modality="MR",
        all_files=[],
        representative_file=tmp_path / "x.dcm",
        file_count=5,
        suggested_datatype=None,
        suggested_suffix=None,
    )
    labeled = _auto_label([group], [])
    assert len(labeled) == 1
    assert labeled[0].datatype is not None
    assert labeled[0].suffix is not None
