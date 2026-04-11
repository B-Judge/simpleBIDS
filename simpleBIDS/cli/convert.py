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
_STATUS_NAME = "conversion_status.json"
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

Partial-failure recovery: if a previous run succeeded for some subjects but
failed for others, re-running bids-convert will skip already-completed
subjects and retry only the failures.  Use --force to convert all subjects
regardless of prior status.

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
  bids-convert /data/my_study --keep-staging   # keep staging tree for debugging
  bids-convert /data/my_study --force          # re-convert even already-done subjects\
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
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Convert all subjects even if they were successfully converted in a "
            "previous run.  By default already-completed subjects are skipped."
        ),
    )
    args = parser.parse_args(argv)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()
    config_path = bids_root / _CONFIG_REL
    cache_dir = bids_root / _CACHE_DIRNAME
    manifest_path = cache_dir / _MANIFEST_NAME

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

    # Load prior conversion status for partial-failure recovery
    already_done: set[tuple[str, str]] = (
        set() if args.force else _load_status(cache_dir)
    )
    if already_done and not args.force:
        print(
            f"\n  Resuming: {len(already_done)} subject/session(s) already converted "
            f"(use --force to re-convert them)."
        )

    ordered = sorted(subject_sessions.items())
    n_total = len(ordered)
    n_skip = sum(1 for (sub, ses), _ in ordered if (sub, ses) in already_done)
    n_todo = n_total - n_skip
    print(f"\nConverting {n_todo} subject/session(s) to BIDS format")
    if n_skip:
        print(f"  ({n_skip} already completed — skipping)")
    print(f"\n  Config:  {config_path}")
    print(f"  Output:  {bids_root}\n")

    completed = set(already_done)
    failed: list[str] = []

    for i, ((sub, ses), staging_dir) in enumerate(ordered, 1):
        label = f"sub-{sub}  ses-{ses}"

        if (sub, ses) in already_done:
            print(f"[{i}/{n_total}]  {label}  (skipped — already done)")
            continue

        print(f"[{i}/{n_total}]  {label}")
        t0 = time.monotonic()

        def _msg(m: str) -> None:
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

        if success:
            completed.add((sub, ses))
            _save_status(cache_dir, completed)
        else:
            failed.append(label)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    all_done = not failed and completed >= set(subject_sessions.keys())
    if all_done and not args.keep_staging:
        cleanup_staging(bids_root)
        print("Staging directory removed.\n")
    elif args.keep_staging:
        print(f"Staging directory preserved at {bids_root / '.simpleBIDS_staging'}\n")

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"{'─' * 60}")
    if failed:
        n_ok = n_total - len(failed)
        print(f"  {n_ok}/{n_total} subject/session(s) converted successfully.")
        print(f"\n  Failed:")
        for f in failed:
            print(f"    {f}")
        print(
            "\n  Tip: ensure dcm2bids or dcm2niix is installed and on your PATH.\n"
            "  Re-run bids-convert to retry only the failed subjects.\n"
            "  Run with --keep-staging to inspect the staging directories.",
            file=sys.stderr,
        )
        sys.exit(1)

    n_newly_done = len(completed) - len(already_done)
    print(f"  All {n_total} subject/session(s) converted successfully.")
    if n_newly_done < n_total:
        print(f"  ({n_newly_done} converted this run, {n_total - n_newly_done} were already done)")
    print(f"\n  BIDS output: {bids_root}")
    print(f"{'─' * 60}")
    print(f"\nNext step:  bids-update-participants {bids_root}\n")


# ---------------------------------------------------------------------------
# Conversion status helpers
# ---------------------------------------------------------------------------

def _load_status(cache_dir: Path) -> set[tuple[str, str]]:
    """Return the set of (subject, session) pairs already successfully converted."""
    status_path = cache_dir / _STATUS_NAME
    if not status_path.exists():
        return set()
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return {(item["subject"], item["session"]) for item in data.get("completed", [])}
    except Exception as exc:
        logger.warning("Could not read conversion status from %s: %s", status_path, exc)
        return set()


def _save_status(cache_dir: Path, completed: set[tuple[str, str]]) -> None:
    """Persist the set of completed (subject, session) pairs."""
    status_path = cache_dir / _STATUS_NAME
    try:
        data = {
            "completed": [
                {"subject": sub, "session": ses}
                for sub, ses in sorted(completed)
            ]
        }
        status_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save conversion status to %s: %s", status_path, exc)


if __name__ == "__main__":
    main()
