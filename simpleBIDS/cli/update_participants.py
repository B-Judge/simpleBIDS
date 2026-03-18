"""bids-update-participants: sync participants.tsv with sub-* directories on disk."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable
from simpleBIDS.utils.logging import configure_logging
from simpleBIDS.utils.progress import ProgressBar

logger = logging.getLogger(__name__)

_WORKFLOW = """\
simpleBIDS workflow (run in order):
  1. bids-init <bids_dir>               — create a new BIDS project
  2. bids-sort <bids_dir>               — scan sourcedata/, group series, build staging
  3. bids-label <bids_dir>              — assign BIDS labels (GUI or --headless)
  4. bids-convert <bids_dir>            — convert staged data to BIDS format
  5. bids-update-participants <bids_dir>— sync participants.tsv with converted data (this command)
"""

_EXAMPLES = """\
examples:
  bids-update-participants /data/my_study
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-update-participants",
        description=(
            "Step 5 of 5 — Synchronize participants.tsv with converted data on disk.\n\n"
            "Walks all sub-* directories in the BIDS project root and merges each\n"
            "discovered participant into participants.tsv:\n\n"
            "  - Adds rows for newly found sub-* directories\n"
            "  - Updates existing rows with current modality information\n"
            "  - Preserves manually added columns (e.g. age, sex, group) — never overwrites them\n"
            "  - Warns about participants present in the TSV but missing from disk\n"
            "    (flags with '?' but does NOT delete them)\n\n"
            "The modalities column lists BIDS datatype folders found under each subject\n"
            "(e.g. 'anat dwi func'). Session-level datatype folders are also collected.\n\n"
            "Safe to run multiple times — idempotent for already-present participants.\n\n"
            "Requires: bids-convert must have been run to produce sub-* output directories."
        ),
        epilog="\n".join([_WORKFLOW, _EXAMPLES]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help="Path to the BIDS project directory (created by bids-init).",
    )
    args = parser.parse_args(argv)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()

    if not bids_root.exists():
        print(
            f"ERROR: {bids_root} does not exist.\n"
            f"Run 'bids-init {args.bids_dir}' to create the project first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not (bids_root / "dataset_description.json").exists():
        print(
            f"ERROR: {bids_root} does not look like a BIDS project "
            "(dataset_description.json not found).\n"
            f"Run 'bids-init {args.bids_dir}' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    tsv_path = bids_root / "participants.tsv"
    table = ParticipantsTable.load(tsv_path)

    added: list[str] = []
    updated: list[str] = []

    sub_dirs = sorted(d for d in bids_root.glob("sub-*") if d.is_dir())
    if not sub_dirs:
        print(
            "No sub-* directories found in the BIDS project.\n"
            f"Run 'bids-convert {bids_root}' to produce converted subject data first."
        )
        sys.exit(0)

    with ProgressBar(total=len(sub_dirs), label="Scanning subjects") as scan_bar:
        for i, sub_dir in enumerate(sub_dirs, 1):
            participant_id = sub_dir.name  # e.g. "sub-001"
            modalities = _collect_modalities(sub_dir)
            extra = {"modalities": " ".join(sorted(modalities))} if modalities else {}

            record = ParticipantRecord(participant_id=participant_id, extra=extra)

            if participant_id in table:
                updated.append(participant_id)
            else:
                added.append(participant_id)

            table.add(record)
            scan_bar.update(i)

    table.save(tsv_path)

    # Summary
    print(f"participants.tsv updated: {tsv_path}")
    print(f"  Added:   {len(added)}")
    for pid in added:
        print(f"    + {pid}")
    print(f"  Updated: {len(updated)}")
    for pid in updated:
        print(f"    ~ {pid}")
    print(f"  Total:   {len(table)} participant(s)")

    # Flag participants in TSV missing from disk
    on_disk = {d.name for d in sub_dirs}
    missing = [pid for pid in _all_ids(table) if pid not in on_disk]
    if missing:
        print(
            f"\nWARNING: {len(missing)} participant(s) present in participants.tsv "
            "but not found on disk (not removed):"
        )
        for pid in missing:
            print(f"    ? {pid}")


def _collect_modalities(sub_dir: Path) -> set[str]:
    """Return the set of BIDS datatype folder names found under sub_dir."""
    datatypes: set[str] = set()
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
    return list(table._records.keys())


if __name__ == "__main__":
    main()
