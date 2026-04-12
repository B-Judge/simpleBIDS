"""Tests for bids/scaffold.py."""

import json
from pathlib import Path

from simpleBIDS.bids.scaffold import scaffold_bids


def test_scaffold_creates_expected_files(tmp_path):
    scaffold_bids(tmp_path, dataset_name="TestDataset")

    assert (tmp_path / "dataset_description.json").exists()
    assert (tmp_path / "participants.tsv").exists()
    assert (tmp_path / "participants.json").exists()
    assert (tmp_path / "README").exists()
    assert (tmp_path / ".bidsignore").exists()
    assert (tmp_path / "code").is_dir()
    assert (tmp_path / "derivatives").is_dir()
    assert (tmp_path / "sourcedata").is_dir()


def test_scaffold_dataset_description_content(tmp_path):
    scaffold_bids(tmp_path, dataset_name="MyStudy", authors=["Alice", "Bob"])
    desc = json.loads((tmp_path / "dataset_description.json").read_text())
    assert desc["Name"] == "MyStudy"
    assert desc["Authors"] == ["Alice", "Bob"]
    assert "BIDSVersion" in desc


def test_scaffold_does_not_overwrite_by_default(tmp_path):
    (tmp_path / "README").write_text("custom content")
    scaffold_bids(tmp_path)
    assert (tmp_path / "README").read_text() == "custom content"


def test_scaffold_overwrites_when_forced(tmp_path):
    (tmp_path / "README").write_text("old")
    scaffold_bids(tmp_path, dataset_name="New", overwrite=True)
    assert "old" not in (tmp_path / "README").read_text()


def test_scaffold_does_not_overwrite_existing_json(tmp_path):
    """_write_json skips existing JSON files when overwrite=False (lines 96-97)."""
    existing = json.dumps({"Name": "Original", "BIDSVersion": "1.0.0"})
    (tmp_path / "dataset_description.json").write_text(existing)
    scaffold_bids(tmp_path, dataset_name="ShouldNotOverwrite")
    loaded = json.loads((tmp_path / "dataset_description.json").read_text())
    assert loaded["Name"] == "Original"
