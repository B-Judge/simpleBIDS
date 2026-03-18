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


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-label",
        description="Assign BIDS datatype/suffix labels to detected series.",
    )
    parser.add_argument("bids_dir", help="Path to the BIDS project directory.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Skip the GUI and apply heuristic auto-labeling only.",
    )
    args = parser.parse_args(argv)

    bids_root = Path(args.bids_dir).resolve()
    cache_dir = bids_root / _CACHE_DIRNAME
    manifest_path = cache_dir / _MANIFEST_NAME

    if not manifest_path.exists():
        print(
            f"ERROR: {manifest_path} not found. Run bids-sort first.",
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
        print(f"Headless labeling complete. Config written to {config_path}")
        print(f"Run: bids-convert {bids_root}")
        return

    # GUI mode
    try:
        from simpleBIDS.gui.app import run_label_gui
    except Exception as exc:
        print(f"ERROR: Could not import GUI: {exc}", file=sys.stderr)
        print("Try --headless for non-interactive use.", file=sys.stderr)
        sys.exit(1)

    labeled = run_label_gui(groups, manifest, bids_root)
    if labeled is None:
        print("Labeling cancelled.")
        sys.exit(0)

    config = build_config(labeled)
    write_config(config, config_path)
    print(f"Config written to {config_path}")
    print(f"Run: bids-convert {bids_root}")


def _group_from_entry(entry: dict) -> SeriesGroup:
    """Reconstruct a SeriesGroup from a manifest entry (paths as strings)."""
    all_files = [Path(f) for f in entry.get("all_files", [])]
    rep = Path(entry["representative_file"]) if entry.get("representative_file") else (all_files[0] if all_files else Path("."))
    staging = Path(entry["staging_dir"]) if entry.get("staging_dir") else None
    g = SeriesGroup(
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
    return g


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
