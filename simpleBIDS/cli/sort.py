"""bids-sort: scan sourcedata/, group series, and build the symlinked staging tree."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

from simpleBIDS.inference.session_inference import infer_session
from simpleBIDS.inference.subject_inference import infer_subject
from simpleBIDS.patterns.series_grouper import SeriesGroup, group_series
from simpleBIDS.patterns.slice_sampler import sample_slice
from simpleBIDS.patterns.symlink_sorter import build_staging
from simpleBIDS.utils.logging import configure_logging
from simpleBIDS.utils.progress import ProgressBar

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_STAGING_DIRNAME = ".simpleBIDS_staging"
_MANIFEST_NAME = "series_manifest.json"

_DESCRIPTION = """\
Step 2 of 5 — Scan sourcedata/ and prepare each series for conversion.

Walks <bids_dir>/sourcedata/, reads DICOM and NIfTI headers, and groups all
files into per-series collections. For each series it:

  1. Reads headers to group files by series (SeriesInstanceUID / filename stem)
  2. Infers subject and session IDs from DICOM tags and file-path patterns
  3. Creates a symlinked staging directory under .simpleBIDS_staging/ so that
     dcm2niix can run on one series at a time with no cross-series mixing
  4. Extracts a representative PNG slice for display in the GUI
  5. Writes .simpleBIDS_cache/series_manifest.json for use by bids-label

Re-running this command is safe — it clears and rebuilds staging and cache.

Prerequisite: run bids-init first and populate sourcedata/ with raw data.\
"""

_EPILOG = """\
workflow:
  1. bids-init <bids_dir>                  create a new BIDS project
  2. bids-sort <bids_dir>                  [YOU ARE HERE] scan & stage series
  3. bids-label <bids_dir>                 assign BIDS labels (GUI or --headless)
  4. bids-convert <bids_dir>               convert staged data to BIDS format
  5. bids-update-participants <bids_dir>   sync participants.tsv with output

what comes next:
  After bids-sort completes, run:
    bids-label <bids_dir>

examples:
  bids-sort /data/my_study
  bids-sort /data/my_study --verbose\
"""


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-sort",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bids_dir",
        nargs="?",
        help=(
            "Required. Path to the BIDS project directory created by bids-init. "
            "sourcedata/ inside this directory will be scanned."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print DEBUG-level messages from the DICOM scanner and grouper.",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger("simpleBIDS").setLevel(logging.DEBUG)

    if args.bids_dir is None:
        parser.print_help()
        print("\nERROR: bids_dir is required.", file=sys.stderr)
        sys.exit(1)

    bids_root = Path(args.bids_dir).resolve()
    sourcedata = bids_root / "sourcedata"

    if not bids_root.exists():
        print(
            f"ERROR: {bids_root} does not exist.\n"
            f"Run 'bids-init {args.bids_dir}' to create the project first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not (bids_root / "dataset_description.json").exists():
        print(
            f"ERROR: {bids_root} does not look like a BIDS project "
            "(dataset_description.json not found).\n"
            f"Run 'bids-init {args.bids_dir}' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not sourcedata.exists():
        print(
            f"ERROR: sourcedata/ not found at {sourcedata}\n"
            "Place your raw DICOM or NIfTI data in sourcedata/ before running bids-sort.",
            file=sys.stderr,
        )
        sys.exit(1)

    cache_dir = bids_root / _CACHE_DIRNAME
    staging_root = bids_root / _STAGING_DIRNAME

    # ── Preserve existing labels before clearing cache ────────────────────────
    # If bids-label has already been run, carry its SeriesDescription→(datatype,
    # suffix) decisions forward as heuristic suggestions in the new manifest.
    # The dcm2bids_config.json itself remains valid and is NOT touched.
    existing_labels: dict[str, tuple[str | None, str | None]] = {}
    config_path = bids_root / "code" / "dcm2bids_config.json"
    if config_path.exists():
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            for entry in config_data.get("descriptions", []):
                desc = entry.get("criteria", {}).get("SeriesDescription")
                if desc:
                    existing_labels[desc] = (
                        entry.get("datatype") or None,
                        entry.get("suffix") or None,
                    )
        except Exception as exc:
            logger.debug("Could not read existing config for label preservation: %s", exc)

    if existing_labels:
        print(
            f"\n  Note: Found existing config with {len(existing_labels)} labeled "
            f"series — previous labels will be applied as suggestions.\n"
            f"  The existing config is still valid; only re-run bids-label if you\n"
            f"  need to label newly added series or change existing assignments.\n"
        )

    # Idempotent: clear and rebuild staging + cache.
    # Also clear conversion status so it doesn't refer to a stale staging tree.
    for d in (cache_dir, staging_root):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    # ── Phase 1: scan and group series ───────────────────────────────────────
    _banner("Phase 1/4 — Scanning source data")
    t0 = time.monotonic()
    with ProgressBar(label="Reading files") as scan_bar:
        series_groups = group_series(sourcedata, progress_callback=scan_bar.update)
    print(f"  Found {len(series_groups)} series  ({time.monotonic() - t0:.1f}s)")

    if not series_groups:
        print(
            "\nNo DICOM or NIfTI series found in sourcedata/.\n"
            "Make sure your raw imaging files are inside sourcedata/ and are\n"
            "readable DICOM (.dcm, .ima) or NIfTI (.nii, .nii.gz) files."
        )
        sys.exit(0)

    # ── Phase 2: infer subject and session IDs ───────────────────────────────
    _banner("Phase 2/4 — Inferring subject and session identifiers")
    t0 = time.monotonic()
    with ProgressBar(total=len(series_groups), label="Inferring IDs") as infer_bar:
        for i, group in enumerate(series_groups):
            meta = group.extra.get("dicom_metadata")
            group.subject_id = infer_subject(meta, group.representative_file)
            group.session_id = infer_session(meta, group.representative_file)
            infer_bar.update(i + 1)
    print(f"  Done  ({time.monotonic() - t0:.1f}s)")

    # Apply previous labeling decisions as suggestions for matching series
    if existing_labels:
        n_matched = 0
        for group in series_groups:
            key = group.series_description or ""
            if key in existing_labels:
                dt, sf = existing_labels[key]
                if dt is not None:
                    group.suggested_datatype = dt
                if sf is not None:
                    group.suggested_suffix = sf
                n_matched += 1
        if n_matched:
            logger.info(
                "Re-applied previous labels to %d/%d series", n_matched, len(series_groups)
            )

    # ── Phase 3: build symlinked staging tree ─────────────────────────────────
    _banner("Phase 3/4 — Building staging directories")
    t0 = time.monotonic()
    with ProgressBar(total=len(series_groups), label="Staging series") as stage_bar:
        build_staging(
            series_groups,
            bids_root,
            staging_root=staging_root,
            progress_callback=stage_bar.update,
        )
    print(f"  Staging root: {staging_root}  ({time.monotonic() - t0:.1f}s)")

    # ── Phase 4: cache representative slices and metadata ────────────────────
    _banner("Phase 4/4 — Extracting preview slices and writing manifest")
    t0 = time.monotonic()
    manifest: list[dict] = []
    with ProgressBar(total=len(series_groups), label="Caching slices") as cache_bar:
        for i, group in enumerate(series_groups):
            entry = _serialize_group(group, i)

            slice_path = cache_dir / f"series_{i:04d}.png"
            try:
                pixels = sample_slice(group.representative_file)
                _save_png(pixels, slice_path)
                entry["slice_png"] = str(slice_path)
            except Exception as exc:
                logger.debug("Could not extract slice for series %d: %s", i, exc)
                entry["slice_png"] = None

            meta_path = cache_dir / f"series_{i:04d}.json"
            meta_path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")
            manifest.append(entry)
            cache_bar.update(i + 1)

    (cache_dir / _MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    print(f"  Manifest: {cache_dir / _MANIFEST_NAME}  ({time.monotonic() - t0:.1f}s)")

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'─' * 72}")
    print(f"  {len(series_groups)} series detected:\n")
    _print_table(series_groups)
    print(f"\n{'─' * 72}")
    print(f"\nNext step:  bids-label {bids_root}\n")


def _banner(text: str) -> None:
    print(f"\n{text}")
    print("─" * len(text))


def _serialize_group(group: SeriesGroup, index: int) -> dict:
    return {
        "index": index,
        "series_description": group.series_description,
        "series_number": group.series_number,
        "modality": group.modality,
        "file_count": group.file_count,
        "representative_file": str(group.representative_file),
        "all_files": [str(f) for f in group.all_files],
        "subject_id": group.subject_id,
        "session_id": group.session_id,
        "suggested_datatype": group.suggested_datatype,
        "suggested_suffix": group.suggested_suffix,
        "is_localizer": group.is_localizer,
        "staging_dir": str(group.staging_dir) if group.staging_dir else None,
        "slug": group.slug,
        "slice_png": None,  # filled in after PNG save
    }


def _save_png(pixels, path: Path) -> None:
    from PIL import Image

    img = Image.fromarray(pixels.astype("uint8"))
    img.save(path)


def _print_table(groups: list[SeriesGroup]) -> None:
    col_sub = 12
    col_ses = 12
    col_mod = 8
    col_files = 6
    header = (
        f"  {'#':>4}  {'Subject':<{col_sub}}  {'Session':<{col_ses}}  "
        f"{'Mod':<{col_mod}}  {'Files':>{col_files}}  Description"
    )
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for i, g in enumerate(groups):
        desc = (g.series_description or "—")[:52]
        loc_flag = " [localizer]" if g.is_localizer else ""
        print(
            f"  {i:>4}  {(g.subject_id or '—'):<{col_sub}}  "
            f"{(g.session_id or '—'):<{col_ses}}  "
            f"{(g.modality or '—'):<{col_mod}}  "
            f"{g.file_count:>{col_files}}  "
            f"{desc}{loc_flag}"
        )


if __name__ == "__main__":
    main()
