"""Tests for bids/converter.py — mocks subprocess and shutil.which."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from simpleBIDS.bids.converter import (
    _update_participants,
    convert_subject,
)
from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_ok(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="done", stderr="")


def _fake_fail(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")


# ---------------------------------------------------------------------------
# _update_participants
# ---------------------------------------------------------------------------


def test_update_participants_creates_new_row(tmp_path: Path) -> None:
    tsv = tmp_path / "participants.tsv"
    _update_participants(tsv, "001", None)
    table = ParticipantsTable.load(tsv)
    assert "sub-001" in table


def test_update_participants_uses_provided_record(tmp_path: Path) -> None:
    tsv = tmp_path / "participants.tsv"
    record = ParticipantRecord(participant_id="sub-999", age="30", sex="F")
    _update_participants(tsv, "001", record)
    table = ParticipantsTable.load(tsv)
    # participant_id should be overwritten to sub-001
    assert "sub-001" in table


def test_update_participants_appends_to_existing(tmp_path: Path) -> None:
    tsv = tmp_path / "participants.tsv"
    table = ParticipantsTable()
    table.add(ParticipantRecord(participant_id="sub-001"))
    table.save(tsv)

    _update_participants(tsv, "002", None)

    loaded = ParticipantsTable.load(tsv)
    assert "sub-001" in loaded
    assert "sub-002" in loaded


def test_update_participants_deduplicates(tmp_path: Path) -> None:
    tsv = tmp_path / "participants.tsv"
    _update_participants(tsv, "001", None)
    _update_participants(tsv, "001", None)
    table = ParticipantsTable.load(tsv)
    assert len(table) == 1


# ---------------------------------------------------------------------------
# convert_subject — dcm2bids path
# ---------------------------------------------------------------------------


def test_convert_subject_uses_dcm2bids_when_available(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    with (
        patch("simpleBIDS.bids.converter.shutil.which", return_value="/usr/bin/dcm2bids"),
        patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_fake_ok),
    ):
        result = convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
        )

    assert result is True
    assert "sub-001" in ParticipantsTable.load(tsv)


def test_convert_subject_dcm2bids_failure_returns_false(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    with (
        patch("simpleBIDS.bids.converter.shutil.which", return_value="/usr/bin/dcm2bids"),
        patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_fake_fail),
    ):
        result = convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
        )

    assert result is False


# ---------------------------------------------------------------------------
# convert_subject — dcm2niix fallback
# ---------------------------------------------------------------------------


def test_convert_subject_falls_back_to_dcm2niix(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    # Add a series subdirectory so dcm2niix gets called at least once
    (staging / "series_001").mkdir(parents=True)
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    def _which(name):
        return None if name == "dcm2bids" else "/usr/bin/dcm2niix"

    with (
        patch("simpleBIDS.bids.converter.shutil.which", side_effect=_which),
        patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_fake_ok),
    ):
        result = convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
        )

    # any_success = True from fake_ok, so result should be True
    assert result is True


def test_convert_subject_returns_false_when_no_tools(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    with patch("simpleBIDS.bids.converter.shutil.which", return_value=None):
        result = convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
        )

    assert result is False


def test_convert_subject_progress_callback_called(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    messages: list[str] = []

    with (
        patch("simpleBIDS.bids.converter.shutil.which", return_value="/usr/bin/dcm2bids"),
        patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_fake_ok),
    ):
        convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
            progress_callback=messages.append,
        )

    assert len(messages) >= 1
    assert any("001" in m for m in messages)


def test_convert_subject_participant_record_id_overridden(tmp_path: Path) -> None:
    """participant_record.participant_id is overwritten to match subject_id."""
    staging = tmp_path / "staging"
    staging.mkdir()
    tsv = tmp_path / "participants.tsv"
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')
    record = ParticipantRecord(participant_id="sub-WRONG", age="25")

    with (
        patch("simpleBIDS.bids.converter.shutil.which", return_value="/usr/bin/dcm2bids"),
        patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_fake_ok),
    ):
        convert_subject(
            subject_id="001",
            session_id="20230101",
            staging_dir=staging,
            bids_root=tmp_path,
            config_path=config,
            participants_path=tsv,
            participant_record=record,
        )

    table = ParticipantsTable.load(tsv)
    assert "sub-001" in table
    assert "sub-WRONG" not in table


# ---------------------------------------------------------------------------
# _run_dcm2niix_fallback helpers (already tested in test_convert.py
# but _place_nifti_files and _match_description covered there)
# ---------------------------------------------------------------------------


def test_dcm2niix_fallback_runs_per_series_dir(tmp_path: Path) -> None:
    """Verify dcm2niix is invoked once per series subdirectory."""
    staging = tmp_path / "staging"
    (staging / "series_001").mkdir(parents=True)
    (staging / "series_002").mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": [{"datatype": "anat", "suffix": "T1w", "criteria": {}}]}')

    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("simpleBIDS.bids.converter.shutil.which", side_effect=lambda n: "/bin/dcm2niix"):
        with patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_run):
            from simpleBIDS.bids.converter import _run_dcm2niix_fallback
            _run_dcm2niix_fallback("001", "20230101", staging, tmp_path, config, print)

    # Two series dirs → two dcm2niix invocations
    assert len(calls) == 2
    assert all("dcm2niix" in c[0] for c in calls)


def test_dcm2niix_fallback_skips_files_in_staging(tmp_path: Path) -> None:
    """Non-directory entries in staging_dir are skipped (line 125 continue branch)."""
    staging = tmp_path / "staging"
    staging.mkdir()
    # Add a file (not a dir) — should be skipped
    (staging / "not_a_dir.txt").write_text("skip me")
    # Add one real series dir
    (staging / "series_001").mkdir()
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("simpleBIDS.bids.converter.shutil.which", return_value="/bin/dcm2niix"):
        with patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_run):
            from simpleBIDS.bids.converter import _run_dcm2niix_fallback
            _run_dcm2niix_fallback("001", "20230101", staging, tmp_path, config, print)

    # Only one call for the one directory
    assert len(calls) == 1


def test_dcm2niix_fallback_logs_warning_on_failure(tmp_path: Path) -> None:
    """When dcm2niix returns non-zero, a warning is logged (line 143)."""
    staging = tmp_path / "staging"
    (staging / "series_001").mkdir(parents=True)
    config = tmp_path / "config.json"
    config.write_text('{"descriptions": []}')

    def _run_fail(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="dcm2niix error")

    with patch("simpleBIDS.bids.converter.shutil.which", return_value="/bin/dcm2niix"):
        with patch("simpleBIDS.bids.converter.subprocess.run", side_effect=_run_fail):
            from simpleBIDS.bids.converter import _run_dcm2niix_fallback
            result = _run_dcm2niix_fallback("001", "20230101", staging, tmp_path, config, print)

    # All series failed → any_success is False
    assert result is False
