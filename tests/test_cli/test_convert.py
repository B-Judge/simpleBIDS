"""Tests for cli/convert.py (bids-convert command).

These tests validate the CLI guard-rails (missing files, missing staging).
Actual dcm2bids/dcm2niix invocation is not tested here — those tools are
optional runtime dependencies not available in the test environment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simpleBIDS.cli.init import main as init_main
from simpleBIDS.cli.convert import main as convert_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(bids_root: Path, staging_dir: Path | None = None) -> None:
    cache = bids_root / ".simpleBIDS_cache"
    cache.mkdir(parents=True, exist_ok=True)
    entry: dict = {"subject_id": "001", "session_id": "20230101"}
    if staging_dir is not None:
        entry["staging_dir"] = str(staging_dir)
    (cache / "series_manifest.json").write_text(
        json.dumps([entry]), encoding="utf-8"
    )


def _write_config(bids_root: Path) -> None:
    code = bids_root / "code"
    code.mkdir(exist_ok=True)
    config = {
        "descriptions": [
            {
                "datatype": "anat",
                "suffix": "T1w",
                "criteria": {"SeriesDescription": "T1w_MPRAGE"},
            }
        ]
    }
    (code / "dcm2bids_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Guard-rail error tests
# ---------------------------------------------------------------------------


def test_convert_errors_if_no_bids_dir_supplied() -> None:
    with pytest.raises(SystemExit) as exc_info:
        convert_main([])
    assert exc_info.value.code != 0


def test_convert_errors_if_bids_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        convert_main([str(tmp_path / "nonexistent")])
    assert exc_info.value.code != 0


def test_convert_errors_if_manifest_missing(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    _write_config(bids)
    # No manifest
    with pytest.raises(SystemExit) as exc_info:
        convert_main([str(bids)])
    assert exc_info.value.code != 0


def test_convert_errors_if_config_missing(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "s001"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    # No config
    with pytest.raises(SystemExit) as exc_info:
        convert_main([str(bids)])
    assert exc_info.value.code != 0


def test_convert_errors_if_manifest_has_no_staging_dirs(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    # Manifest present but no staging_dir entries
    _write_manifest(bids, staging_dir=None)
    _write_config(bids)
    with pytest.raises(SystemExit) as exc_info:
        convert_main([str(bids)])
    assert exc_info.value.code != 0


def test_convert_errors_if_empty_manifest(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    cache = bids / ".simpleBIDS_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "series_manifest.json").write_text("[]")
    _write_config(bids)
    with pytest.raises(SystemExit) as exc_info:
        convert_main([str(bids)])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# _load_config helper (tested via converter module)
# ---------------------------------------------------------------------------


def test_load_config_returns_empty_on_missing_file(tmp_path: Path) -> None:
    from simpleBIDS.bids.converter import _load_config
    result = _load_config(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_config_returns_parsed_dict(tmp_path: Path) -> None:
    from simpleBIDS.bids.converter import _load_config
    cfg = {"descriptions": [{"datatype": "anat", "suffix": "T1w", "criteria": {}}]}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    result = _load_config(cfg_path)
    assert result["descriptions"][0]["suffix"] == "T1w"


# ---------------------------------------------------------------------------
# _match_description helper
# ---------------------------------------------------------------------------


def test_match_description_matches_by_substring() -> None:
    from simpleBIDS.bids.converter import _match_description
    descriptions = [
        {"datatype": "anat", "suffix": "T1w", "criteria": {"SeriesDescription": "T1w_MPRAGE"}},
        {"datatype": "func", "suffix": "bold", "criteria": {"SeriesDescription": "BOLD_rest"}},
    ]
    result = _match_description("T1w_MPRAGE_1", descriptions)
    assert result is not None
    assert result["suffix"] == "T1w"


def test_match_description_case_insensitive() -> None:
    from simpleBIDS.bids.converter import _match_description
    descriptions = [
        {"datatype": "anat", "suffix": "T1w", "criteria": {"SeriesDescription": "T1w_MPRAGE"}},
    ]
    result = _match_description("t1w_mprage_1", descriptions)
    assert result is not None


def test_match_description_single_fallback() -> None:
    from simpleBIDS.bids.converter import _match_description
    descriptions = [
        {"datatype": "anat", "suffix": "T1w", "criteria": {"SeriesDescription": "T1w"}},
    ]
    result = _match_description("completely_different_name", descriptions)
    assert result is not None


def test_match_description_returns_none_when_no_match() -> None:
    from simpleBIDS.bids.converter import _match_description
    descriptions = [
        {"datatype": "anat", "suffix": "T1w", "criteria": {"SeriesDescription": "T1w"}},
        {"datatype": "func", "suffix": "bold", "criteria": {"SeriesDescription": "BOLD"}},
    ]
    result = _match_description("unknown_xyz_series", descriptions)
    assert result is None


def test_match_description_empty_descriptions() -> None:
    from simpleBIDS.bids.converter import _match_description
    assert _match_description("T1w_1", []) is None


# ---------------------------------------------------------------------------
# _build_bids_filename helper
# ---------------------------------------------------------------------------


def test_build_bids_filename_basic() -> None:
    from simpleBIDS.bids.converter import _build_bids_filename
    name = _build_bids_filename("001", "20230101", {}, "T1w")
    assert name == "sub-001_ses-20230101_T1w"


def test_build_bids_filename_with_task_entity() -> None:
    from simpleBIDS.bids.converter import _build_bids_filename
    name = _build_bids_filename("001", "20230101", {"task": "rest"}, "bold")
    assert "task-rest" in name
    assert name.startswith("sub-001_ses-20230101_task-rest_bold")


def test_build_bids_filename_entity_order() -> None:
    from simpleBIDS.bids.converter import _build_bids_filename
    name = _build_bids_filename(
        "001", "20230101", {"run": "01", "acq": "highres"}, "T1w"
    )
    parts = name.split("_")
    acq_pos = next(i for i, p in enumerate(parts) if p.startswith("acq-"))
    run_pos = next(i for i, p in enumerate(parts) if p.startswith("run-"))
    assert acq_pos < run_pos  # acq before run per BIDS spec


def test_build_bids_filename_unknown_entities_excluded() -> None:
    from simpleBIDS.bids.converter import _build_bids_filename
    # 'foo' is not a known BIDS entity key and should be silently ignored
    name = _build_bids_filename("001", "20230101", {"foo": "bar"}, "T1w")
    assert "foo" not in name


# ---------------------------------------------------------------------------
# _place_nifti_files helper
# ---------------------------------------------------------------------------


def test_place_nifti_files_moves_nifti_and_sidecar(tmp_path: Path) -> None:
    from simpleBIDS.bids.converter import _place_nifti_files

    src_dir = tmp_path / "series_tmp"
    src_dir.mkdir()
    (src_dir / "T1w_MPRAGE_1.nii.gz").write_bytes(b"fake_nifti")
    (src_dir / "T1w_MPRAGE_1.json").write_text('{"TR": 2.0}')

    bids_root = tmp_path / "bids"
    descriptions = [
        {
            "datatype": "anat",
            "suffix": "T1w",
            "criteria": {"SeriesDescription": "T1w_MPRAGE"},
            "custom_entities": {},
        }
    ]
    _place_nifti_files(src_dir, "001", "20230101", bids_root, descriptions, print)

    dest_dir = bids_root / "sub-001" / "ses-20230101" / "anat"
    assert dest_dir.is_dir()
    nii_files = list(dest_dir.glob("*.nii.gz"))
    json_files = list(dest_dir.glob("*.json"))
    assert len(nii_files) == 1
    assert len(json_files) == 1


def test_place_nifti_files_skips_unmatched(tmp_path: Path) -> None:
    from simpleBIDS.bids.converter import _place_nifti_files

    src_dir = tmp_path / "series_tmp"
    src_dir.mkdir()
    (src_dir / "UnknownSeries_1.nii.gz").write_bytes(b"data")

    bids_root = tmp_path / "bids"
    descriptions = [
        {"datatype": "anat", "suffix": "T1w", "criteria": {"SeriesDescription": "T1w"}},
        {"datatype": "func", "suffix": "bold", "criteria": {"SeriesDescription": "BOLD"}},
    ]
    _place_nifti_files(src_dir, "001", "20230101", bids_root, descriptions, lambda m: None)

    # Nothing placed — bids_root should not contain sub-* dirs
    sub_dirs = list(bids_root.glob("sub-*"))
    assert sub_dirs == []


# ---------------------------------------------------------------------------
# Full conversion loop — mock convert_subject
# ---------------------------------------------------------------------------


def test_convert_main_runs_convert_subject(tmp_path: Path) -> None:
    """The main convert loop calls convert_subject for each subject/session."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])

    # Set up staging dir that the manifest points to
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    with patch("simpleBIDS.cli.convert.convert_subject", return_value=True) as mock_conv:
        convert_main([str(bids), "--keep-staging"])

    assert mock_conv.called


def test_convert_main_success_prints_summary(tmp_path: Path, capsys) -> None:
    """Successful conversion prints a summary without errors."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    with patch("simpleBIDS.cli.convert.convert_subject", return_value=True):
        convert_main([str(bids), "--keep-staging"])

    captured = capsys.readouterr()
    assert "successfully" in captured.out.lower() or "OK" in captured.out


def test_convert_main_progress_callback_is_called(tmp_path: Path, capsys) -> None:
    """The _msg closure (line 156) is exercised when convert_subject calls it."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    def _conv_with_callback(subject_id, session_id, staging_dir, bids_root,
                             config_path, participants_path, *,
                             progress_callback=None, **kwargs):
        if progress_callback:
            progress_callback(f"Processing sub-{subject_id}")
        return True

    with patch("simpleBIDS.cli.convert.convert_subject", side_effect=_conv_with_callback):
        convert_main([str(bids), "--keep-staging"])

    captured = capsys.readouterr()
    assert "Processing" in captured.out


def test_convert_main_failure_exits_nonzero(tmp_path: Path) -> None:
    """When convert_subject returns False the CLI exits non-zero."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    with patch("simpleBIDS.cli.convert.convert_subject", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            convert_main([str(bids), "--keep-staging"])

    assert exc_info.value.code != 0


def test_convert_keep_staging_flag_preserves_directory(tmp_path: Path) -> None:
    """--keep-staging prevents cleanup_staging from being called."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    with (
        patch("simpleBIDS.cli.convert.convert_subject", return_value=True),
        patch("simpleBIDS.cli.convert.cleanup_staging") as mock_cleanup,
    ):
        convert_main([str(bids), "--keep-staging"])

    mock_cleanup.assert_not_called()


def test_convert_without_keep_staging_calls_cleanup(tmp_path: Path) -> None:
    """Without --keep-staging, cleanup_staging is called."""
    from unittest.mock import patch

    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    staging = bids / ".simpleBIDS_staging" / "sub001_ses01"
    staging.mkdir(parents=True)
    _write_manifest(bids, staging_dir=staging)
    _write_config(bids)

    with (
        patch("simpleBIDS.cli.convert.convert_subject", return_value=True),
        patch("simpleBIDS.cli.convert.cleanup_staging") as mock_cleanup,
    ):
        convert_main([str(bids)])

    mock_cleanup.assert_called_once()
