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


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-convert",
        description="Convert staged data to BIDS format using dcm2bids_config.json.",
    )
    parser.add_argument("bids_dir", help="Path to the BIDS project directory.")
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Do not remove the staging directory after conversion.",
    )
    args = parser.parse_args(argv)

    bids_root = Path(args.bids_dir).resolve()
    config_path = bids_root / _CONFIG_REL
    manifest_path = bids_root / _CACHE_DIRNAME / _MANIFEST_NAME

    if not config_path.exists():
        print(
            f"ERROR: {config_path} not found. Run bids-label first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not manifest_path.exists():
        print(
            f"ERROR: {manifest_path} not found. Run bids-sort first.",
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
            staging_path = Path(staging)
            # Use the parent of the per-series dir as the subject/session staging root
            key = (sub, ses)
            if key not in subject_sessions:
                subject_sessions[key] = staging_path.parent

    if not subject_sessions:
        print("No subject/session staging directories found in manifest.", file=sys.stderr)
        sys.exit(1)

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
        print(f"  sub-{sub} ses-{ses}: {status}")
        if not success:
            any_failed = True

    if not args.keep_staging:
        cleanup_staging(bids_root)
        print("Staging directory removed.")

    if any_failed:
        print("\nOne or more subjects failed conversion.", file=sys.stderr)
        sys.exit(1)

    print(f"\nConversion complete. BIDS data written to {bids_root}")
    print(f"Run: bids-update-participants {bids_root}")


if __name__ == "__main__":
    main()
