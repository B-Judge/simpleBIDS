"""Build a per-series symlinked staging directory for clean dcm2niix runs."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from simpleBIDS.patterns.series_grouper import SeriesGroup

logger = logging.getLogger(__name__)

_STAGING_DIRNAME = ".simpleBIDS_staging"


def build_staging(
    series_groups: list[SeriesGroup],
    output_root: Path,
    *,
    staging_root: Path | None = None,
) -> dict[int, Path]:
    """Create symlinked staging subdirectories for each series.

    Each :class:`SeriesGroup` gets its own subdirectory under *staging_root*,
    populated with relative symlinks pointing back to the original files.
    This lets ``dcm2niix`` run cleanly on one series at a time with no
    cross-series contamination.

    The ``staging_dir`` attribute of each :class:`SeriesGroup` is updated in
    place.

    Args:
        series_groups: Series to stage; modified in place (``staging_dir`` set).
        output_root: BIDS output directory; staging is placed adjacent unless
            *staging_root* is given explicitly.
        staging_root: Override the staging directory location.

    Returns:
        Mapping of ``id(series_group)`` → its staging subdirectory path.
    """
    if staging_root is None:
        staging_root = output_root / _STAGING_DIRNAME

    staging_root.mkdir(parents=True, exist_ok=True)
    logger.info("Building staging directory at %s", staging_root)

    result: dict[int, Path] = {}

    for group in series_groups:
        series_dir = _series_dir(staging_root, group)
        series_dir.mkdir(parents=True, exist_ok=True)

        for source_file in group.all_files:
            link = series_dir / source_file.name
            if link.exists() or link.is_symlink():
                link.unlink()
            try:
                link.symlink_to(_relative_target(link, source_file))
            except Exception as exc:
                logger.warning("Could not symlink %s → %s: %s", link, source_file, exc)

        group.staging_dir = series_dir
        result[id(group)] = series_dir
        logger.debug("Staged %d files → %s", group.file_count, series_dir)

    return result


def cleanup_staging(output_root: Path, *, staging_root: Path | None = None) -> None:
    """Remove the staging directory after successful conversion.

    Args:
        output_root: BIDS output directory (used to locate staging if
            *staging_root* is not given).
        staging_root: Override the staging directory location.
    """
    if staging_root is None:
        staging_root = output_root / _STAGING_DIRNAME
    if staging_root.exists():
        shutil.rmtree(staging_root)
        logger.info("Removed staging directory %s", staging_root)


def _series_dir(staging_root: Path, group: SeriesGroup) -> Path:
    """Return the per-series subdirectory path (not yet created)."""
    parts: list[str] = []
    if group.subject_id:
        parts.append(group.subject_id)
    if group.session_id:
        parts.append(group.session_id)
    parts.append(group.slug)
    return staging_root / "_".join(parts)


def _relative_target(link: Path, target: Path) -> Path:
    """Compute a relative path from *link*'s parent to *target*."""
    try:
        return Path(
            "../" * len(link.parent.relative_to(link.parent).parts)
        ) / target.resolve().relative_to(link.parent.resolve())
    except ValueError:
        # Targets outside the tree — fall back to absolute symlink
        return target.resolve()
