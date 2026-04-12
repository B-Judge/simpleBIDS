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


def test_load_skips_rows_with_empty_participant_id(tmp_path):
    """Rows where participant_id is blank are skipped (line 62 branch)."""
    tsv = tmp_path / "participants.tsv"
    tsv.write_text("participant_id\tage\n\t25\nsub-001\t30\n", encoding="utf-8")
    table = ParticipantsTable.load(tsv)
    assert len(table) == 1
    assert "sub-001" in table


def test_load_handles_corrupt_file(tmp_path):
    """A file that raises during reading returns an empty table (lines 71-72)."""
    tsv = tmp_path / "participants.tsv"
    tsv.write_bytes(b"\xff\xfe corrupt binary")
    # Should not raise; returns empty table
    table = ParticipantsTable.load(tsv)
    assert isinstance(table, ParticipantsTable)
