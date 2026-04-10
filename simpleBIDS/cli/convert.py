"""bids-convert: run BIDS conversion using the config produced by bids-label."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from simpleBIDS.bids.converter import convert_subject
from simpleBIDS.patterns.symlink_sorter import cleanup_staging
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_MANIFEST_NAME = "series_manifest.json"
_CONFIG_REL = Path("code") / "dcm2bids_config.json"

_DESCRIPTION = """\
Step 4 of 5 — Convert staged data to BIDS format.

Reads code/dcm2bids_config.json (written by bids-label) and the series manifest
from .simpleBIDS_cache/, then converts each subject/session in turn:

  Preferred:  dcm2bids  — wraps dcm2niix and handles BIDS renaming automatically
  Fallback:   dcm2niix  — called directly; output placed in the BIDS tree using
                          the config's SeriesDescription criteria

Conversion is run per staging series directory so that dcm2niix never sees
files from a different series.

After all subjects convert successfully, .simpleBIDS_staging/ is removed
(pass --keep-staging to preserve it for debugging).

Runtime requirements (not hard-coded — checked at call time):
  dcm2bids  preferred  pip install dcm2bids
  dcm2niix  fallback   https://github.com/rordenlab/dcm2niix

Prerequisite: run bids-sort and bids-label first.\
"""

_EPILOG = """\
workflow:
  1. bids-init <bids_dir>                  create a new BIDS project
  2. bids-sort <bids_dir>                  scan & stage series
  3. bids-label <bids_dir>                 assign BIDS labels
  4. bids-convert <bids_dir>               [YOU ARE HERE] convert to BIDS
  5. bids-update-participants <bids_dir>   sync participants.tsv with output

what comes next:
  After bids-convert completes successfully, run:
    bids-update-participants <bids_dir>

examples:
  bids-convert /data/my_study
  bids-convert /data/my_study --keep-staging   # keep staging tree for debugging\
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-convert",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Required. Path to the BIDS project directory (created by bids-init). "
            "bids-sort and bids-label must have been run first."
        ),
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help=(
            "Do not delete .simpleBIDS_staging/ after conversion. "
            "Useful for inspecting dcm2niix output or re-running conversion manually."
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

    # Collect unique (subject_id, session_id) → staging_dir pairs from the manifest
    subject_sessions: dict[tuple[str, str], Path] = {}
    for entry in manifest:
        sub = entry.get("subject_id") or "unknown"
        ses = entry.get("session_id") or "01"
        staging = entry.get("staging_dir")
        if staging:
            key = (sub, ses)
            if key not in subject_sessions:
                subject_sessions[key] = Path(staging).parent

    if not subject_sessions:
        print(
            "ERROR: No staging directories found in the series manifest.\n"
            f"Re-run 'bids-sort {bids_root}' to rebuild the staging tree.",
            file=sys.stderr,
        )
        sys.exit(1)

    ordered = sorted(subject_sessions.items())
    n_total = len(ordered)
    print(f"\nConverting {n_total} subject/session(s) to BIDS format\n")
    print(f"  Config:  {config_path}")
    print(f"  Output:  {bids_root}\n")

    failed: list[str] = []

    for i, ((sub, ses), staging_dir) in enumerate(ordered, 1):
        label = f"sub-{sub}  ses-{ses}"
        print(f"[{i}/{n_total}]  {label}")
        t0 = time.monotonic()

        def _msg(m: str, _label: str = label) -> None:
            print(f"         {m}")

        success = convert_subject(
            subject_id=sub,
            session_id=ses,
            staging_dir=staging_dir,
            bids_root=bids_root,
            config_path=config_path,
            participants_path=participants_path,
            progress_callback=_msg,
        )

        elapsed = time.monotonic() - t0
        status = "OK" if success else "FAILED"
        print(f"         {status}  ({elapsed:.1f}s)\n")

        if not success:
            failed.append(f"sub-{sub}  ses-{ses}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if not args.keep_staging:
        cleanup_staging(bids_root)
        print("Staging directory removed.\n")
    else:
        print(f"Staging directory preserved at {bids_root / '.simpleBIDS_staging'}\n")

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"{'─' * 60}")
    if failed:
        print(f"  {n_total - len(failed)}/{n_total} subject/session(s) converted successfully.")
        print(f"\n  Failed:")
        for f in failed:
            print(f"    {f}")
        print(
            "\n  Tip: ensure dcm2bids or dcm2niix is installed and on your PATH.\n"
            "  Run with --keep-staging to inspect the staging directories.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"  All {n_total} subject/session(s) converted successfully.")
    print(f"\n  BIDS output: {bids_root}")
    print(f"{'─' * 60}")
    print(f"\nNext step:  bids-update-participants {bids_root}\n")


if __name__ == "__main__":
    main()
