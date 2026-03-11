"""Tests for bids/participants.py."""

from pathlib import Path

from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable


def test_add_and_save(tmp_path):
    table = ParticipantsTable()
    table.add(ParticipantRecord(participant_id="sub-001", age="25", sex="F"))
    table.add(ParticipantRecord(participant_id="sub-002", age="30", sex="M"))

    path = tmp_path / "participants.tsv"
    table.save(path)
    assert path.exists()

    loaded = ParticipantsTable.load(path)
    assert len(loaded) == 2
    assert "sub-001" in loaded


def test_deduplication():
    table = ParticipantsTable()
    table.add(ParticipantRecord(participant_id="sub-001", age="25"))
    table.add(ParticipantRecord(participant_id="sub-001", age="26"))
    assert len(table) == 1


def test_load_missing_file(tmp_path):
    table = ParticipantsTable.load(tmp_path / "nonexistent.tsv")
    assert len(table) == 0
