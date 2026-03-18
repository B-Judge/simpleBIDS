"""bids-init: scaffold a new BIDS project directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simpleBIDS.bids.scaffold import scaffold_bids
from simpleBIDS.utils.logging import configure_logging


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-init",
        description="Scaffold a new BIDS project directory.",
    )
    parser.add_argument("bids_dir", help="Path to the new BIDS project directory.")
    parser.add_argument("--name", help="Dataset name (skips interactive prompt).")
    args = parser.parse_args(argv)

    bids_root = Path(args.bids_dir).resolve()

    if (bids_root / "dataset_description.json").exists():
        print(f"ERROR: {bids_root} already contains a BIDS project.", file=sys.stderr)
        sys.exit(1)

    dataset_name = args.name
    if not dataset_name:
        dataset_name = input("Dataset name: ").strip() or "Untitled Dataset"

    scaffold_bids(bids_root, dataset_name=dataset_name)
    print(f"BIDS project created at {bids_root}")
    print(f"Place raw neuroimaging data in: {bids_root / 'sourcedata'}")
    print(f"Then run: bids-sort {bids_root}")


if __name__ == "__main__":
    main()
