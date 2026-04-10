"""bids-init: scaffold a new BIDS project directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simpleBIDS.bids.scaffold import scaffold_bids
from simpleBIDS.utils.logging import configure_logging

_DESCRIPTION = """\
Step 1 of 5 — Create a new BIDS project directory.

Scaffolds the standard BIDS top-level structure at <bids_dir>:

  dataset_description.json   study metadata (name, authors, BIDS version)
  participants.tsv            subject registry (grows as data is converted)
  participants.json           column definitions for participants.tsv
  README                      free-text project notes
  .bidsignore                 patterns excluded from BIDS validation
  code/                       scripts and conversion configs (dcm2bids_config.json)
  derivatives/                processed outputs (not raw data)
  sourcedata/                 drop your raw DICOM or NIfTI data here

After running this command, place your raw data in sourcedata/ then run bids-sort.\
"""

_EPILOG = """\
workflow:
  1. bids-init <bids_dir>                  [YOU ARE HERE] create a new BIDS project
  2. bids-sort <bids_dir>                  scan & stage series
  3. bids-label <bids_dir>                 assign BIDS labels (GUI or --headless)
  4. bids-convert <bids_dir>               convert staged data to BIDS format
  5. bids-update-participants <bids_dir>   sync participants.tsv with output

what comes next:
  1. Place raw DICOM or NIfTI files inside <bids_dir>/sourcedata/
  2. Run:  bids-sort <bids_dir>

examples:
  bids-init /data/my_study
  bids-init /data/my_study --name "Resting State Cohort 2024"\
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-init",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Required. Path where the BIDS project will be created. "
            "The directory (and its parents) will be made if they do not exist."
        ),
    )
    parser.add_argument(
        "--name",
        metavar="DATASET_NAME",
        help=(
            "Dataset name written to dataset_description.json. "
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
            "Choose a different path or remove the directory to start fresh.",
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

    print(f"\nCreating BIDS project at {bids_root} …")
    scaffold_bids(bids_root, dataset_name=dataset_name)

    print(f"  dataset_description.json   ← Name: \"{dataset_name}\"")
    print(f"  participants.tsv")
    print(f"  participants.json")
    print(f"  README")
    print(f"  .bidsignore")
    print(f"  code/")
    print(f"  derivatives/")
    print(f"  sourcedata/               ← place raw data here")
    print(f"\nBIDS project ready.\n")
    print(f"Next steps:")
    print(f"  1. Copy your raw DICOM or NIfTI data into:  {bids_root / 'sourcedata'}")
    print(f"  2. Run:  bids-sort {bids_root}\n")


if __name__ == "__main__":
    main()
