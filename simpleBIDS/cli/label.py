"""bids-label: open the GUI (or run headless) to assign BIDS labels to each series."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from simpleBIDS.bids.config_builder import LabeledSeries, build_config, write_config
from simpleBIDS.patterns.series_grouper import SeriesGroup
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_MANIFEST_NAME = "series_manifest.json"
_CONFIG_REL = Path("code") / "dcm2bids_config.json"

_WORKFLOW = """\
simpleBIDS workflow (run in order):
  1. bids-init <bids_dir>               — create a new BIDS project
  2. bids-sort <bids_dir>               — scan sourcedata/, group series, build staging
  3. bids-label <bids_dir>              — assign BIDS labels (GUI or --headless) (this command)
  4. bids-convert <bids_dir>            — convert staged data to BIDS format
  5. bids-update-participants <bids_dir>— sync participants.tsv with converted data
"""

_EXAMPLES = """\
examples:
  bids-label /data/my_study              # opens tkinter GUI
  bids-label /data/my_study --headless   # auto-label with heuristics, no GUI
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-label",
        description=(
            "Step 3 of 5 — Assign BIDS datatype and suffix labels to each detected series.\n\n"
            "Reads the series manifest produced by bids-sort and presents each series\n"
            "for labeling. By default opens a tkinter GUI showing:\n"
            "  - A representative image slice from each series\n"
            "  - The inferred series description, modality, subject, and session\n"
            "  - Dropdown menus for BIDS datatype (anat, func, dwi, fmap, …)\n"
            "    and suffix (T1w, bold, dwi, …) populated from the BIDS schema\n"
            "  - Required entity fields (e.g. task name for func/bold)\n\n"
            "On completion, writes code/dcm2bids_config.json for use by bids-convert.\n\n"
            "Use --headless to skip the GUI and apply heuristic auto-labeling.\n"
            "Heuristics are based on SeriesDescription keywords and Modality tags;\n"
            "review the generated config before running bids-convert.\n\n"
            "Requires: bids-sort must have been run successfully."
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
        "--headless",
        action="store_true",
        help=(
            "Skip the GUI and apply heuristic auto-labeling based on series descriptions "
            "and DICOM Modality tags. Writes the config and exits immediately. "
            "Suitable for automated or batch pipelines."
        ),
    )
    args = parser.parse_args(argv)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()
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
            f"Run 'bids-sort {bids_root}' to scan and group your source data first.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = [_group_from_entry(e) for e in manifest]
    config_path = bids_root / _CONFIG_REL

    if args.headless:
        labeled = _auto_label(groups, manifest)
        config = build_config(labeled)
        write_config(config, config_path)
        print(f"Headless labeling complete ({len(labeled)} series labeled).")
        print(f"Config written to {config_path}")
        print(f"\nReview the config, then run: bids-convert {bids_root}")
        return

    # GUI mode
    try:
        from simpleBIDS.gui.app import run_label_gui
    except Exception as exc:
        print(
            f"ERROR: Could not load the GUI: {exc}\n"
            "Possible causes:\n"
            "  - tkinter is not installed (install python3-tk via your package manager)\n"
            "  - Running in a headless environment with no display\n"
            "Use --headless to label without a GUI.",
            file=sys.stderr,
        )
        sys.exit(1)

    labeled = run_label_gui(groups, manifest, bids_root)
    if labeled is None:
        print("Labeling cancelled. Run bids-label again to resume.")
        sys.exit(0)

    config = build_config(labeled)
    write_config(config, config_path)
    print(f"Config written to {config_path}")
    print(f"\nNext step: bids-convert {bids_root}")


def _group_from_entry(entry: dict) -> SeriesGroup:
    """Reconstruct a SeriesGroup from a manifest entry (paths as strings)."""
    all_files = [Path(f) for f in entry.get("all_files", [])]
    rep = (
        Path(entry["representative_file"])
        if entry.get("representative_file")
        else (all_files[0] if all_files else Path("."))
    )
    staging = Path(entry["staging_dir"]) if entry.get("staging_dir") else None
    return SeriesGroup(
        series_description=entry.get("series_description"),
        series_number=entry.get("series_number"),
        modality=entry.get("modality"),
        all_files=all_files,
        representative_file=rep,
        file_count=entry.get("file_count", len(all_files)),
        subject_id=entry.get("subject_id"),
        session_id=entry.get("session_id"),
        suggested_datatype=entry.get("suggested_datatype"),
        suggested_suffix=entry.get("suggested_suffix"),
        is_localizer=entry.get("is_localizer", False),
        staging_dir=staging,
    )


def _auto_label(groups: list[SeriesGroup], manifest: list[dict]) -> list[LabeledSeries]:
    """Apply heuristic suggestions without user input."""
    labeled: list[LabeledSeries] = []
    for group in groups:
        datatype = group.suggested_datatype or "anat"
        suffix = group.suggested_suffix or "T1w"
        labeled.append(LabeledSeries(series_group=group, datatype=datatype, suffix=suffix))
        logger.info(
            "Auto-labeled '%s' → %s/%s",
            group.series_description,
            datatype,
            suffix,
        )
    return labeled


if __name__ == "__main__":
    main()
