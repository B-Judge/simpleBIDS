"""bids-convert: run BIDS conversion using the config produced by bids-label."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from simpleBIDS.bids.converter import convert_subject
from simpleBIDS.patterns.symlink_sorter import cleanup_staging
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_MANIFEST_NAME = "series_manifest.json"
_CONFIG_REL = Path("code") / "dcm2bids_config.json"

_WORKFLOW = """\
simpleBIDS workflow (run in order):
  1. bids-init <bids_dir>               — create a new BIDS project
  2. bids-sort <bids_dir>               — scan sourcedata/, group series, build staging
  3. bids-label <bids_dir>              — assign BIDS labels (GUI or --headless)
  4. bids-convert <bids_dir>            — convert staged data to BIDS format (this command)
  5. bids-update-participants <bids_dir>— sync participants.tsv with converted data
"""

_EXAMPLES = """\
examples:
  bids-convert /data/my_study
  bids-convert /data/my_study --keep-staging   # preserve .simpleBIDS_staging/ after conversion
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-convert",
        description=(
            "Step 4 of 5 — Convert staged data to BIDS format.\n\n"
            "Reads code/dcm2bids_config.json (produced by bids-label) and the series\n"
            "manifest from .simpleBIDS_cache/, then converts each subject/session:\n\n"
            "  - Preferred: uses dcm2bids (wraps dcm2niix with BIDS renaming)\n"
            "  - Fallback:  calls dcm2niix directly, then places files into the\n"
            "               BIDS subject/session tree\n\n"
            "Conversion runs per staging series directory for clean isolation.\n"
            "On success, the staging directory (.simpleBIDS_staging/) is removed\n"
            "unless --keep-staging is passed.\n\n"
            "Runtime requirements (checked at call time, not hard dependencies):\n"
            "  dcm2bids  — preferred (pip install dcm2bids)\n"
            "  dcm2niix  — fallback  (https://github.com/rordenlab/dcm2niix)\n\n"
            "Requires: bids-sort and bids-label must have been run successfully."
        ),
        epilog="\n".join([_WORKFLOW, _EXAMPLES]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help="Path to the BIDS project directory (created by bids-init).",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help=(
            "Do not delete .simpleBIDS_staging/ after conversion. "
            "Useful for debugging conversion failures or re-running dcm2niix manually."
        ),
    )
    args = parser.parse_args(argv)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()
    config_path = bids_root / _CONFIG_REL
    manifest_path = bids_root / _CACHE_DIRNAME / _MANIFEST_NAME

    if not bids_root.exists():
        print(
            f"ERROR: {bids_root} does not exist.\n"
            f"Run 'bids-init {args.bids_dir}' to create the project first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not manifest_path.exists():
        print(
            f"ERROR: Series manifest not found at {manifest_path}\n"
            f"Run 'bids-sort {bids_root}' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not config_path.exists():
        print(
            f"ERROR: Conversion config not found at {config_path}\n"
            f"Run 'bids-label {bids_root}' to generate it first.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    participants_path = bids_root / "participants.tsv"

    # Collect unique (subject_id, session_id) → staging_dir pairs
    subject_sessions: dict[tuple[str, str], Path] = {}
    for entry in manifest:
        sub = entry.get("subject_id") or "unknown"
        ses = entry.get("session_id") or "01"
        staging = entry.get("staging_dir")
        if staging:
            key = (sub, ses)
            if key not in subject_sessions:
                # Use the parent of the per-series dir as the subject/session staging root
                subject_sessions[key] = Path(staging).parent

    if not subject_sessions:
        print(
            "ERROR: No staging directories found in the series manifest.\n"
            f"Re-run 'bids-sort {bids_root}' to rebuild the staging tree.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Converting {len(subject_sessions)} subject/session(s) …\n")
    any_failed = False
    for (sub, ses), staging_dir in sorted(subject_sessions.items()):
        success = convert_subject(
            subject_id=sub,
            session_id=ses,
            staging_dir=staging_dir,
            bids_root=bids_root,
            config_path=config_path,
            participants_path=participants_path,
            progress_callback=print,
        )
        status = "OK" if success else "FAILED"
        print(f"  sub-{sub}  ses-{ses}: {status}")
        if not success:
            any_failed = True

    if not args.keep_staging:
        cleanup_staging(bids_root)
        print("\nStaging directory removed.")
    else:
        print(f"\nStaging directory preserved at {bids_root / '.simpleBIDS_staging'}")

    if any_failed:
        print(
            "\nOne or more subjects failed conversion.\n"
            "Check the log output above for details.\n"
            "Tip: ensure dcm2bids or dcm2niix is installed and on your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\nConversion complete. BIDS data written to {bids_root}")
    print(f"Next step: bids-update-participants {bids_root}")


if __name__ == "__main__":
    main()
