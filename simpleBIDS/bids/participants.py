"""Read, update, and persist the BIDS participants.tsv file."""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = ["participant_id"]


@dataclass
class ParticipantRecord:
    """A single row in participants.tsv."""

    participant_id: str
    age: str | None = None
    sex: str | None = None
    # Any additional columns passed as keyword arguments land here
    extra: dict = field(default_factory=dict)

    def to_row(self, columns: list[str]) -> dict[str, str]:
        base = {
            "participant_id": self.participant_id,
            "age": self.age or "n/a",
            "sex": self.sex or "n/a",
        }
        base.update(self.extra)
        return {col: str(base.get(col, "n/a")) for col in columns}


class ParticipantsTable:
    """In-memory representation of ``participants.tsv``.

    Example::

        table = ParticipantsTable.load(bids_root / "participants.tsv")
        table.add(ParticipantRecord(participant_id="sub-001", age="25", sex="F"))
        table.save(bids_root / "participants.tsv")
    """

    def __init__(self, records: list[ParticipantRecord] | None = None) -> None:
        self._records: dict[str, ParticipantRecord] = {}
        for record in records or []:
            self._records[record.participant_id] = record

    @classmethod
    def load(cls, path: Path) -> "ParticipantsTable":
        """Load from an existing participants.tsv, or return an empty table."""
        if not path.exists():
            return cls()
        records: list[ParticipantRecord] = []
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    pid = row.pop("participant_id", "").strip()
                    if not pid:
                        continue
                    records.append(
                        ParticipantRecord(
                            participant_id=pid,
                            age=row.pop("age", None) or None,
                            sex=row.pop("sex", None) or None,
                            extra=dict(row),
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to read %s: %s — starting fresh", path, exc)
        return cls(records)

    def add(self, record: ParticipantRecord) -> None:
        """Add or update a participant record (keyed on ``participant_id``)."""
        self._records[record.participant_id] = record

    def __contains__(self, participant_id: str) -> bool:
        return participant_id in self._records

    def __len__(self) -> int:
        return len(self._records)

    @property
    def columns(self) -> list[str]:
        """Sorted union of all columns present across all records."""
        cols: set[str] = {"participant_id", "age", "sex"}
        for r in self._records.values():
            cols.update(r.extra.keys())
        ordered = _REQUIRED_COLUMNS + sorted(cols - set(_REQUIRED_COLUMNS))
        return ordered

    def save(self, path: Path) -> None:
        """Write the table to *path* as a tab-separated file."""
        cols = self.columns
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
            writer.writeheader()
            for record in sorted(self._records.values(), key=lambda r: r.participant_id):
                writer.writerow(record.to_row(cols))
        logger.info("Saved %d participants to %s", len(self._records), path)
