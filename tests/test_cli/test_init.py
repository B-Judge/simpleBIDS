"""Tests for cli/init.py (bids-init command)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simpleBIDS.cli.init import main


def test_init_creates_standard_structure(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    main([str(bids), "--name", "TestStudy"])

    assert (bids / "dataset_description.json").exists()
    assert (bids / "participants.tsv").exists()
    assert (bids / "participants.json").exists()
    assert (bids / "README").exists()
    assert (bids / ".bidsignore").exists()
    assert (bids / "code").is_dir()
    assert (bids / "derivatives").is_dir()
    assert (bids / "sourcedata").is_dir()


def test_init_dataset_name_written_to_description(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    main([str(bids), "--name", "Resting State 2024"])
    desc = json.loads((bids / "dataset_description.json").read_text())
    assert desc["Name"] == "Resting State 2024"
    assert "BIDSVersion" in desc


def test_init_creates_directory_if_missing(tmp_path: Path) -> None:
    bids = tmp_path / "does" / "not" / "exist" / "yet"
    main([str(bids), "--name", "Test"])
    assert bids.is_dir()


def test_init_errors_on_existing_bids_project(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    bids.mkdir()
    (bids / "dataset_description.json").write_text('{"Name": "old"}')
    with pytest.raises(SystemExit) as exc_info:
        main([str(bids), "--name", "New"])
    assert exc_info.value.code != 0


def test_init_errors_when_no_bids_dir_supplied() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code != 0


def test_init_idempotent_does_not_overwrite_readme(tmp_path: Path) -> None:
    """Re-running bids-init is blocked by existing dataset_description.json."""
    bids = tmp_path / "study"
    main([str(bids), "--name", "First"])
    # Attempting again on the same directory must exit non-zero
    with pytest.raises(SystemExit) as exc_info:
        main([str(bids), "--name", "Second"])
    assert exc_info.value.code != 0


def test_init_authors_flag_not_present_bids_version_still_written(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    main([str(bids), "--name", "NoAuthors"])
    desc = json.loads((bids / "dataset_description.json").read_text())
    assert "BIDSVersion" in desc
