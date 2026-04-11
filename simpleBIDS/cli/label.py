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
from simpleBIDS.utils.progress import ProgressBar

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_MANIFEST_NAME = "series_manifest.json"
_CONFIG_REL = Path("code") / "dcm2bids_config.json"

_DESCRIPTION = """\
Step 3 of 5 — Assign BIDS datatype and suffix labels to each series.

Reads the series manifest produced by bids-sort and presents each series for
labeling. By default opens an interactive tkinter GUI that shows:

  • A representative image slice for each series
  • The inferred series description, modality, subject ID, and session ID
  • Dropdown menus for BIDS datatype (anat, func, dwi, fmap, perf, …) and
    suffix (T1w, bold, dwi, …) — values sourced from the bundled BIDS schema
  • Required entity fields rendered dynamically (e.g. task name for func/bold)
  • "Apply to all matching" checkbox for bulk-labeling identical series

On completion, writes code/dcm2bids_config.json for use by bids-convert.

Use --headless to skip the GUI and apply keyword-based heuristics instead.
Review the generated config carefully before running bids-convert.

Prerequisite: run bids-sort first.\
"""

_EPILOG = """\
workflow:
  1. bids-init <bids_dir>                  create a new BIDS project
  2. bids-sort <bids_dir>                  scan & stage series
  3. bids-label <bids_dir>                 [YOU ARE HERE] assign BIDS labels
  4. bids-convert <bids_dir>               convert staged data to BIDS format
  5. bids-update-participants <bids_dir>   sync participants.tsv with output

what comes next:
  After bids-label completes (GUI closed or --headless finished), run:
    bids-convert <bids_dir>

examples:
  bids-label /data/my_study              # interactive GUI
  bids-label /data/my_study --headless   # heuristic auto-labeling, no GUI\
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-label",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Required. Path to the BIDS project directory (created by bids-init). "
            "bids-sort must have been run so that .simpleBIDS_cache/series_manifest.json exists."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Skip the GUI. Apply heuristic auto-labeling based on SeriesDescription "
            "keywords and DICOM Modality tags, then write the config and exit. "
            "Suitable for automated pipelines. Always review the config before converting."
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

    print(f"Loading series manifest ({manifest_path.name}) …")
    manifest: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = [_group_from_entry(e) for e in manifest]
    print(f"  {len(groups)} series loaded.")
    config_path = bids_root / _CONFIG_REL

    if args.headless:
        _run_headless(groups, manifest, config_path, bids_root)
        return

    # ── GUI mode ──────────────────────────────────────────────────────────────
    try:
        from simpleBIDS.gui.app import run_label_gui
    except Exception as exc:
        print(
            f"ERROR: Could not load the GUI: {exc}\n"
            "Possible causes:\n"
            "  - tkinter is not installed (install python3-tk via your package manager)\n"
            "  - Running in a headless environment (no display / SSH without -X)\n"
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
    print(f"\nConfig written to {config_path}")
    print(f"\nNext step:  bids-convert {bids_root}\n")


def _run_headless(
    groups: list[SeriesGroup],
    manifest: list[dict],
    config_path: Path,
    bids_root: Path,
) -> None:
    """Auto-label all series from heuristics and write the config.

    Localizer/scout series are silently skipped — they are not valid BIDS
    series and dcm2bids would place them in its temporary directory anyway.
    """
    print("\nHeadless labeling — applying heuristic rules …")
    labeled: list[LabeledSeries] = []
    skipped_localizers: list[str] = []

    with ProgressBar(total=len(groups), label="Labeling series") as bar:
        for i, group in enumerate(groups):
            if group.is_localizer:
                skipped_localizers.append(group.series_description or "?")
                logger.info(
                    "Skipping localizer/scout series '%s'", group.series_description
                )
                bar.update(i + 1)
                continue
            datatype = group.suggested_datatype or "anat"
            suffix = group.suggested_suffix or "T1w"
            labeled.append(
                LabeledSeries(series_group=group, datatype=datatype, suffix=suffix)
            )
            logger.debug(
                "Auto-labeled '%s' → %s/%s",
                group.series_description,
                datatype,
                suffix,
            )
            bar.update(i + 1)

    config = build_config(labeled)
    write_config(config, config_path)

    # Print a compact summary table
    print(f"\n  {'Series description':<40}  {'Datatype':<10}  Suffix")
    print(f"  {'-' * 40}  {'-' * 10}  ------")
    for ls in labeled:
        desc = (ls.series_group.series_description or "—")[:40]
        print(f"  {desc:<40}  {ls.datatype:<10}  {ls.suffix}")

    print(f"\n  {len(labeled)} series labeled.")
    if skipped_localizers:
        print(
            f"  {len(skipped_localizers)} localizer/scout series skipped "
            f"(not valid BIDS series):"
        )
        for desc in skipped_localizers:
            print(f"    ✕ {desc}")
    print(f"  Config written to {config_path}")
    print(
        "\n  Review the config before converting — heuristics may misidentify\n"
        "  unusual or site-specific sequences.\n"
    )
    print(f"Next step:  bids-convert {bids_root}\n")


def _group_from_entry(entry: dict) -> SeriesGroup:
    """Reconstruct a SeriesGroup from a manifest entry (paths as strings)."""
    all_files = [Path(f) for f in entry.get("all_files", [])]
    rep_str = entry.get("representative_file")
    if rep_str:
        rep = Path(rep_str)
    elif all_files:
        rep = all_files[0]
    else:
        logger.warning(
            "Manifest entry '%s' has no file paths; representative_file set to '.'",
            entry.get("series_description", "?"),
        )
        rep = Path(".")
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
    """Apply heuristic suggestions without user input (used by tests)."""
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
