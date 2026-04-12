"""Tests for cli/update_participants.py (bids-update-participants command)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from simpleBIDS.cli.init import main as init_main
from simpleBIDS.cli.update_participants import (
    main as update_main,
    _collect_modalities,
    _collect_sessions,
    _update_sessions_tsv,
)


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


# ---------------------------------------------------------------------------
# _collect_sessions helper (Issue 3)
# ---------------------------------------------------------------------------


def test_collect_sessions_returns_session_tuples(tmp_path: Path) -> None:
    """_collect_sessions returns (session_id, modalities) tuples for each ses-* dir."""
    sub = tmp_path / "sub-001"
    (sub / "ses-01" / "anat").mkdir(parents=True)
    (sub / "ses-01" / "func").mkdir(parents=True)
    (sub / "ses-02" / "dwi").mkdir(parents=True)
    sessions = _collect_sessions(sub)
    assert len(sessions) == 2
    session_ids = [s[0] for s in sessions]
    assert "ses-01" in session_ids
    assert "ses-02" in session_ids
    ses01_mods = next(mods for sid, mods in sessions if sid == "ses-01")
    assert "anat" in ses01_mods
    assert "func" in ses01_mods


def test_collect_sessions_empty_when_no_sessions(tmp_path: Path) -> None:
    """_collect_sessions returns empty list when no ses-* directories exist."""
    sub = tmp_path / "sub-001"
    (sub / "anat").mkdir(parents=True)
    sessions = _collect_sessions(sub)
    assert sessions == []


# ---------------------------------------------------------------------------
# _update_sessions_tsv helper (Issue 3)
# ---------------------------------------------------------------------------


def test_update_sessions_tsv_creates_file(tmp_path: Path) -> None:
    """_update_sessions_tsv creates a sessions.tsv for the subject."""
    sub = tmp_path / "sub-001"
    sub.mkdir()
    sessions = [("ses-01", {"anat"}), ("ses-02", {"func"})]
    _update_sessions_tsv(sub, sessions)
    tsv_path = sub / "sub-001_sessions.tsv"
    assert tsv_path.exists()
    content = tsv_path.read_text()
    assert "ses-01" in content
    assert "ses-02" in content
    assert "anat" in content
    assert "func" in content


def test_update_sessions_tsv_preserves_extra_columns(tmp_path: Path) -> None:
    """Existing user-added columns in sessions.tsv are preserved on update."""
    sub = tmp_path / "sub-001"
    sub.mkdir()
    tsv_path = sub / "sub-001_sessions.tsv"
    # Pre-populate with a custom acq_time column
    tsv_path.write_text(
        "session_id\tmodalities\tacq_time\nses-01\tanat\t2023-01-01T10:00:00\n",
        encoding="utf-8",
    )
    sessions = [("ses-01", {"anat"}), ("ses-02", {"func"})]
    _update_sessions_tsv(sub, sessions)
    content = tsv_path.read_text()
    assert "acq_time" in content
    assert "2023-01-01T10:00:00" in content


def test_update_sessions_tsv_idempotent(tmp_path: Path) -> None:
    """Calling _update_sessions_tsv twice produces the same number of rows."""
    sub = tmp_path / "sub-001"
    sub.mkdir()
    sessions = [("ses-01", {"anat"}), ("ses-02", {"func"})]
    _update_sessions_tsv(sub, sessions)
    _update_sessions_tsv(sub, sessions)
    tsv_path = sub / "sub-001_sessions.tsv"
    with tsv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    # Should be exactly 2 data rows (one per session), not 4
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Integration: sessions.tsv written by bids-update-participants (Issue 3)
# ---------------------------------------------------------------------------


def test_update_creates_sessions_tsv_for_multi_session(tmp_path: Path) -> None:
    """bids-update-participants creates sessions.tsv for multi-session subjects."""
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    sub_dir = bids / "sub-001"
    (sub_dir / "ses-01" / "anat").mkdir(parents=True)
    (sub_dir / "ses-02" / "func").mkdir(parents=True)
    update_main([str(bids)])
    tsv_path = sub_dir / "sub-001_sessions.tsv"
    assert tsv_path.exists(), "sessions.tsv must be created for multi-session subject"
    content = tsv_path.read_text()
    assert "ses-01" in content
    assert "ses-02" in content


def test_update_no_sessions_tsv_for_single_session(tmp_path: Path) -> None:
    """bids-update-participants does NOT create sessions.tsv for single-session subjects."""
    bids = tmp_path / "study"
    init_main([str(bids), "--name", "Test"])
    sub_dir = bids / "sub-001"
    (sub_dir / "ses-01" / "anat").mkdir(parents=True)
    update_main([str(bids)])
    tsv_path = sub_dir / "sub-001_sessions.tsv"
    assert not tsv_path.exists(), (
        "sessions.tsv must NOT be created when there is only one session"
    )
