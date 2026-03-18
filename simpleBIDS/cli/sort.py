"""bids-sort: scan sourcedata/, group series, and build the symlinked staging tree."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from simpleBIDS.inference.session_inference import infer_session
from simpleBIDS.inference.subject_inference import infer_subject
from simpleBIDS.patterns.series_grouper import SeriesGroup, group_series
from simpleBIDS.patterns.slice_sampler import sample_slice
from simpleBIDS.patterns.symlink_sorter import build_staging
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)

_CACHE_DIRNAME = ".simpleBIDS_cache"
_STAGING_DIRNAME = ".simpleBIDS_staging"
_MANIFEST_NAME = "series_manifest.json"


def main(argv=None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="bids-sort",
        description="Scan sourcedata/, group series, and build the symlinked staging tree.",
    )
    parser.add_argument("bids_dir", help="Path to the BIDS project directory.")
    args = parser.parse_args(argv)

    bids_root = Path(args.bids_dir).resolve()
    sourcedata = bids_root / "sourcedata"

    if not bids_root.exists():
        print(f"ERROR: {bids_root} does not exist.", file=sys.stderr)
        sys.exit(1)
    if not sourcedata.exists():
        print(
            f"ERROR: {sourcedata} does not exist. "
            "Run bids-init first, then place raw data in sourcedata/.",
            file=sys.stderr,
        )
        sys.exit(1)

    cache_dir = bids_root / _CACHE_DIRNAME
    staging_root = bids_root / _STAGING_DIRNAME

    # Idempotent: clear and rebuild staging + cache
    for d in (cache_dir, staging_root):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    print(f"Scanning {sourcedata} …")
    series_groups = group_series(sourcedata)

    if not series_groups:
        print("No DICOM or NIfTI series found in sourcedata/.")
        sys.exit(0)

    # Infer subject/session for each group
    for group in series_groups:
        meta = group.extra.get("dicom_metadata")
        group.subject_id = infer_subject(meta, group.representative_file)
        group.session_id = infer_session(meta, group.representative_file)

    # Build staging tree
    build_staging(series_groups, bids_root, staging_root=staging_root)

    # Save cache: image slices (PNG) + per-series metadata JSON + manifest
    manifest: list[dict] = []
    for i, group in enumerate(series_groups):
        entry = _serialize_group(group, i)

        # Save representative slice as PNG
        slice_path = cache_dir / f"series_{i:04d}.png"
        try:
            pixels = sample_slice(group.representative_file)
            _save_png(pixels, slice_path)
            entry["slice_png"] = str(slice_path)
        except Exception as exc:
            logger.warning("Could not extract slice for series %d: %s", i, exc)
            entry["slice_png"] = None

        # Save per-series metadata JSON
        meta_path = cache_dir / f"series_{i:04d}.json"
        meta_path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")

        manifest.append(entry)

    (cache_dir / _MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )

    # Summary table
    print(f"\nFound {len(series_groups)} series:\n")
    _print_table(series_groups)
    print(f"\nManifest written to {cache_dir / _MANIFEST_NAME}")
    print(f"Staging directory: {staging_root}")
    print(f"\nRun: bids-label {bids_root}")


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
    import numpy as np

    img = Image.fromarray(pixels.astype("uint8"))
    img.save(path)


def _print_table(groups: list[SeriesGroup]) -> None:
    header = f"{'#':>4}  {'Subject':<12}  {'Session':<12}  {'Modality':<8}  {'Files':>6}  {'Description'}"
    print(header)
    print("-" * len(header))
    for i, g in enumerate(groups):
        desc = (g.series_description or "")[:48]
        print(
            f"{i:>4}  {(g.subject_id or ''):<12}  {(g.session_id or ''):<12}  "
            f"{(g.modality or ''):<8}  {g.file_count:>6}  {desc}"
        )


if __name__ == "__main__":
    main()
