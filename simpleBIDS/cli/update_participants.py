"""bids-update-participants: sync participants.tsv with sub-* directories on disk."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-update-participants",
        description="Synchronize participants.tsv with sub-* directories found on disk.",
    )
    parser.add_argument("bids_dir", help="Path to the BIDS project directory.")
    args = parser.parse_args(argv)

    bids_root = Path(args.bids_dir).resolve()
    tsv_path = bids_root / "participants.tsv"

    if not bids_root.exists():
        print(f"ERROR: {bids_root} does not exist.", file=sys.stderr)
        sys.exit(1)

    table = ParticipantsTable.load(tsv_path)
    before_count = len(table)

    added: list[str] = []
    updated: list[str] = []

    for sub_dir in sorted(bids_root.glob("sub-*")):
        if not sub_dir.is_dir():
            continue
        participant_id = sub_dir.name  # e.g. "sub-001"

        # Collect modalities by walking datatype subdirectories
        modalities = _collect_modalities(sub_dir)
        extra = {"modalities": " ".join(sorted(modalities))} if modalities else {}

        record = ParticipantRecord(
            participant_id=participant_id,
            extra=extra,
        )

        if participant_id in table:
            updated.append(participant_id)
        else:
            added.append(participant_id)

        table.add(record)

    table.save(tsv_path)

    # Summary
    after_count = len(table)
    print(f"participants.tsv updated: {tsv_path}")
    print(f"  Added:   {len(added)}")
    if added:
        for pid in added:
            print(f"    + {pid}")
    print(f"  Updated: {len(updated)}")
    if updated:
        for pid in updated:
            print(f"    ~ {pid}")
    print(f"  Total:   {after_count} participants")

    # Flag participants in TSV that are missing from disk
    on_disk = {d.name for d in bids_root.glob("sub-*") if d.is_dir()}
    missing = [pid for pid in _all_ids(table) if pid not in on_disk]
    if missing:
        print(f"\nWARNING: {len(missing)} participant(s) in TSV but missing from disk:")
        for pid in missing:
            print(f"    ? {pid}")


def _collect_modalities(sub_dir: Path) -> set[str]:
    """Return the set of BIDS datatype folder names found under sub_dir."""
    datatypes: set[str] = set()
    # Walk session dirs or directly under sub dir
    for child in sub_dir.iterdir():
        if child.is_dir():
            if child.name.startswith("ses-"):
                for ses_child in child.iterdir():
                    if ses_child.is_dir() and not ses_child.name.startswith("."):
                        datatypes.add(ses_child.name)
            elif not child.name.startswith("."):
                datatypes.add(child.name)
    return datatypes


def _all_ids(table: ParticipantsTable) -> list[str]:
    """Return all participant IDs stored in the table."""
    # Access internal dict directly (same module)
    return list(table._records.keys())


if __name__ == "__main__":
    main()
