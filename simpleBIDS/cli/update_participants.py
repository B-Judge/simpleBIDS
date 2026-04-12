"""bids-update-participants: sync participants.tsv with sub-* directories on disk."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable
from simpleBIDS.utils.logging import configure_logging
from simpleBIDS.utils.progress import ProgressBar

logger = logging.getLogger(__name__)

_DESCRIPTION = """\
Step 5 of 5 — Synchronize participants.tsv with converted data on disk.

Walks all sub-* directories in the BIDS project and merges each discovered
participant into participants.tsv:

  +  New sub-* directories are added as new rows
  ~  Existing rows are updated with current modality information
     (e.g. 'anat dwi func' — derived from BIDS datatype folder names)
  ?  Participants in the TSV but absent on disk are flagged with a warning
     and left in place — they are never deleted automatically

For subjects with two or more sessions, a per-subject sessions file is also
created or updated:
  sub-<id>/sub-<id>_sessions.tsv   (session_id + modalities columns)

Custom columns added manually (age, sex, group, …) are preserved; this
command never overwrites values it did not write itself.

Safe to run multiple times — already-present participants are updated, not
duplicated.

Prerequisite: run bids-convert first to produce sub-* output directories.\
"""

_EPILOG = """\
workflow:
  1. bids-init <bids_dir>                  create a new BIDS project
  2. bids-sort <bids_dir>                  scan & stage series
  3. bids-label <bids_dir>                 assign BIDS labels
  4. bids-convert <bids_dir>               convert staged data to BIDS format
  5. bids-update-participants <bids_dir>   [YOU ARE HERE] sync participants.tsv

what comes next:
  Your BIDS dataset is ready. Run the BIDS Validator to check it:
    https://bids-standard.github.io/bids-validator/

examples:
  bids-update-participants /data/my_study\
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-update-participants",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Required. Path to the BIDS project directory (created by bids-init). "
            "sub-* directories produced by bids-convert must be present."
        ),
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

    sub_dirs = sorted(d for d in bids_root.glob("sub-*") if d.is_dir())
    if not sub_dirs:
        print(
            "No sub-* directories found in the BIDS project.\n"
            f"Run 'bids-convert {bids_root}' to produce converted subject data first."
        )
        sys.exit(0)

    added: list[str] = []
    updated: list[str] = []
    sessions_updated: list[str] = []

    print(f"\nScanning {len(sub_dirs)} subject director{'y' if len(sub_dirs) == 1 else 'ies'} …\n")
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

            # Create/update sessions.tsv for multi-session subjects
            sessions = _collect_sessions(sub_dir)
            if len(sessions) >= 2:
                _update_sessions_tsv(sub_dir, sessions)
                sessions_updated.append(participant_id)

            scan_bar.update(i)

    table.save(tsv_path)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\nparticipants.tsv updated: {tsv_path}\n")

    if added:
        print(f"  Added ({len(added)}):")
        for pid in added:
            print(f"    + {pid}")
    if updated:
        print(f"  Updated ({len(updated)}):")
        for pid in updated:
            print(f"    ~ {pid}")

    print(f"\n  Total: {len(table)} participant(s)")

    if sessions_updated:
        print(f"\n  sessions.tsv created/updated for {len(sessions_updated)} multi-session subject(s):")
        for pid in sessions_updated:
            print(f"    {pid}/{pid}_sessions.tsv")

    # Flag participants in TSV missing from disk
    on_disk = {d.name for d in sub_dirs}
    missing = [pid for pid in _all_ids(table) if pid not in on_disk]
    if missing:
        print(
            f"\n  WARNING: {len(missing)} participant(s) in participants.tsv "
            "but not found on disk (not removed):"
        )
        for pid in missing:
            print(f"    ? {pid}")

    print(f"\nYour BIDS dataset is ready at {bids_root}")
    print("Run the BIDS Validator to verify:  https://bids-standard.github.io/bids-validator/\n")


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


def _collect_sessions(sub_dir: Path) -> list[tuple[str, set[str]]]:
    """Return a list of (session_id, modalities) for each ses-* dir under sub_dir."""
    sessions: list[tuple[str, set[str]]] = []
    for child in sorted(sub_dir.iterdir()):
        if child.is_dir() and child.name.startswith("ses-"):
            modalities: set[str] = set()
            for ses_child in child.iterdir():
                if ses_child.is_dir() and not ses_child.name.startswith("."):
                    modalities.add(ses_child.name)
            sessions.append((child.name, modalities))
    return sessions


def _update_sessions_tsv(
    sub_dir: Path,
    sessions: list[tuple[str, set[str]]],
) -> None:
    """Create or update ``sub-<id>/sub-<id>_sessions.tsv`` for a multi-session subject.

    Existing rows are merged with newly discovered sessions; manually added
    columns (e.g. ``acq_time``) are preserved.  The ``modalities`` column is
    always refreshed from disk.
    """
    sub_id = sub_dir.name  # e.g. "sub-001"
    tsv_path = sub_dir / f"{sub_id}_sessions.tsv"

    # Load existing rows so we can preserve user-added columns
    existing: dict[str, dict[str, str]] = {}
    extra_cols: list[str] = []
    if tsv_path.exists():
        try:
            with tsv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                fieldnames = reader.fieldnames or []
                extra_cols = [c for c in fieldnames if c not in ("session_id", "modalities")]
                for row in reader:
                    ses_id = row.get("session_id", "").strip()
                    if ses_id:
                        existing[ses_id] = dict(row)
        except Exception as exc:
            logger.warning("Could not read %s — starting fresh: %s", tsv_path, exc)

    # Merge discovered sessions into the existing rows
    for ses_id, modalities in sessions:
        row = existing.get(ses_id, {"session_id": ses_id})
        row["session_id"] = ses_id
        row["modalities"] = " ".join(sorted(modalities)) if modalities else "n/a"
        existing[ses_id] = row

    # Write out, keeping required columns first then any extra user columns
    cols = ["session_id", "modalities"] + extra_cols
    with tsv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=cols, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for ses_id in sorted(existing):
            writer.writerow({col: existing[ses_id].get(col, "n/a") for col in cols})

    logger.info("Updated %s", tsv_path)


def _all_ids(table: ParticipantsTable) -> list[str]:
    """Return all participant IDs stored in the table."""
    return list(table)


if __name__ == "__main__":
    main()
