"""bids-init: scaffold a new BIDS project directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simpleBIDS.bids.scaffold import scaffold_bids
from simpleBIDS.utils.logging import configure_logging

_WORKFLOW = """\
simpleBIDS workflow (run in order):
  1. bids-init <bids_dir>               — create a new BIDS project (this command)
  2. bids-sort <bids_dir>               — scan sourcedata/, group series, build staging
  3. bids-label <bids_dir>              — assign BIDS labels (GUI or --headless)
  4. bids-convert <bids_dir>            — convert staged data to BIDS format
  5. bids-update-participants <bids_dir>— sync participants.tsv with converted data
"""

_EXAMPLES = """\
examples:
  bids-init /data/my_study
  bids-init /data/my_study --name "Resting State Cohort 2024"
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-init",
        description=(
            "Step 1 of 5 — Create a new BIDS project directory.\n\n"
            "Scaffolds the standard BIDS top-level structure:\n"
            "  dataset_description.json, participants.tsv, participants.json,\n"
            "  README, .bidsignore, and the code/, derivatives/, sourcedata/ folders.\n\n"
            "After running this command, place your raw neuroimaging data\n"
            "(DICOM or NIfTI) inside the sourcedata/ subdirectory, then run bids-sort."
        ),
        epilog="\n".join([_WORKFLOW, _EXAMPLES]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Path where the BIDS project will be created. "
            "The directory will be made if it does not exist."
        ),
    )
    parser.add_argument(
        "--name",
        metavar="DATASET_NAME",
        help=(
            "Dataset name written into dataset_description.json. "
            "If omitted, you will be prompted interactively."
        ),
    )
    args = parser.parse_args(argv)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()

    if (bids_root / "dataset_description.json").exists():
        print(
            f"ERROR: {bids_root} already contains a BIDS project "
            "(dataset_description.json exists).\n"
            "To start fresh, remove the directory first or choose a different path.",
            file=sys.stderr,
        )
        sys.exit(1)

    dataset_name = args.name
    if not dataset_name:
        try:
            dataset_name = input("Dataset name: ").strip() or "Untitled Dataset"
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)

    scaffold_bids(bids_root, dataset_name=dataset_name)
    print(f"BIDS project created at {bids_root}")
    print(f"\nNext steps:")
    print(f"  1. Place raw neuroimaging data in: {bids_root / 'sourcedata'}")
    print(f"  2. Run: bids-sort {bids_root}")


if __name__ == "__main__":
    main()
