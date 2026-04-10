"""Tests for cli/update_participants.py (bids-update-participants command)."""

from __future__ import annotations

from pathlib import Path

import pytest

from simpleBIDS.cli.init import main as init_main
from simpleBIDS.cli.update_participants import main as update_main, _collect_modalities


# ---------------------------------------------------------------------------
# Error guard-rails
# ---------------------------------------------------------------------------


def test_update_errors_if_no_bids_dir_supplied() -> None:
    with pytest.raises(SystemExit) as exc_info:
        update_main([])
    assert exc_info.value.code != 0


def test_update_errors_if_bids_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        update_main([str(tmp_path / "nonexistent")])
    assert exc_info.value.code != 0


def test_update_errors_if_not_a_bids_project(tmp_path: Path) -> None:
    non_bids = tmp_path / "raw"
    non_bids.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        update_main([str(non_bids)])
    assert exc_info.value.code != 0


def test_update_exits_zero_when_no_subjects(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    with pytest.raises(SystemExit) as exc_info:
        update_main([str(bids)])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Adding and updating participants
# ---------------------------------------------------------------------------


def test_update_adds_subjects_to_tsv(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    for sub_id in ["001", "002", "003"]:
        (bids / f"sub-{sub_id}" / "anat").mkdir(parents=True)
    update_main([str(bids)])
    tsv = (bids / "participants.tsv").read_text()
    assert "sub-001" in tsv
    assert "sub-002" in tsv
    assert "sub-003" in tsv


def test_update_records_modalities(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    (bids / "sub-001" / "anat").mkdir(parents=True)
    (bids / "sub-001" / "func").mkdir(parents=True)
    update_main([str(bids)])
    tsv = (bids / "participants.tsv").read_text()
    assert "anat" in tsv
    assert "func" in tsv


def test_update_idempotent(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    (bids / "sub-001" / "anat").mkdir(parents=True)
    update_main([str(bids)])
    update_main([str(bids)])
    tsv = (bids / "participants.tsv").read_text()
    # sub-001 should appear exactly once (header line + one data row)
    lines = [ln for ln in tsv.splitlines() if "sub-001" in ln]
    assert len(lines) == 1


def test_update_preserves_custom_columns(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])

    # Manually add a participant with a custom age column
    (bids / "participants.tsv").write_text(
        "participant_id\tage\nsub-001\t25\n", encoding="utf-8"
    )
    (bids / "sub-001" / "anat").mkdir(parents=True)
    update_main([str(bids)])

    tsv = (bids / "participants.tsv").read_text()
    # age column must still be present
    assert "age" in tsv


def test_update_handles_session_level_datatypes(tmp_path: Path) -> None:
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    # Session-level layout: sub-001/ses-01/anat/
    (bids / "sub-001" / "ses-01" / "anat").mkdir(parents=True)
    (bids / "sub-001" / "ses-01" / "dwi").mkdir(parents=True)
    update_main([str(bids)])
    tsv = (bids / "participants.tsv").read_text()
    assert "sub-001" in tsv
    assert "anat" in tsv
    assert "dwi" in tsv


def test_update_flags_missing_from_disk(tmp_path: Path) -> None:
    """Participants in the TSV but absent on disk should be warned about (but not removed)."""
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    # Pre-populate TSV with a participant that has no directory
    (bids / "participants.tsv").write_text(
        "participant_id\nsub-ghost\n", encoding="utf-8"
    )
    (bids / "sub-001" / "anat").mkdir(parents=True)
    update_main([str(bids)])
    tsv = (bids / "participants.tsv").read_text()
    # sub-ghost should still be in the TSV (not deleted)
    assert "sub-ghost" in tsv
    # sub-001 should now also be present
    assert "sub-001" in tsv


# ---------------------------------------------------------------------------
# _collect_modalities helper
# ---------------------------------------------------------------------------


def test_collect_modalities_flat_layout(tmp_path: Path) -> None:
    sub = tmp_path / "sub-001"
    (sub / "anat").mkdir(parents=True)
    (sub / "func").mkdir(parents=True)
    mods = _collect_modalities(sub)
    assert "anat" in mods
    assert "func" in mods


def test_collect_modalities_session_layout(tmp_path: Path) -> None:
    sub = tmp_path / "sub-001"
    (sub / "ses-01" / "dwi").mkdir(parents=True)
    (sub / "ses-02" / "anat").mkdir(parents=True)
    mods = _collect_modalities(sub)
    assert "dwi" in mods
    assert "anat" in mods


def test_collect_modalities_ignores_hidden_dirs(tmp_path: Path) -> None:
    sub = tmp_path / "sub-001"
    (sub / ".hidden").mkdir(parents=True)
    (sub / "anat").mkdir(parents=True)
    mods = _collect_modalities(sub)
    assert ".hidden" not in mods
    assert "anat" in mods


def test_collect_modalities_empty_subject(tmp_path: Path) -> None:
    sub = tmp_path / "sub-001"
    sub.mkdir()
    mods = _collect_modalities(sub)
    assert mods == set()
