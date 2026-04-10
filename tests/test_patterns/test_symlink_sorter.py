"""Tests for symlink_sorter."""

from pathlib import Path

from simpleBIDS.patterns.series_grouper import SeriesGroup
from simpleBIDS.patterns.symlink_sorter import build_staging, cleanup_staging


def _make_group(tmp_path: Path, name: str, n_files: int = 3) -> SeriesGroup:
    source_dir = tmp_path / "source" / name
    source_dir.mkdir(parents=True)
    files = []
    for i in range(n_files):
        f = source_dir / f"IM{i:04d}.dcm"
        f.write_bytes(b"\x00" * 4)
        files.append(f)
    return SeriesGroup(
        series_description=name,
        series_number=1,
        modality="MR",
        all_files=files,
        representative_file=files[0],
        file_count=n_files,
    )


def test_build_staging_creates_symlinks(tmp_path):
    group = _make_group(tmp_path, "T1w_MPRAGE")
    output = tmp_path / "bids"
    build_staging([group], output)

    assert group.staging_dir is not None
    assert group.staging_dir.is_dir()
    links = list(group.staging_dir.iterdir())
    assert len(links) == 3
    assert all(l.is_symlink() for l in links)


def test_build_staging_sets_staging_dir(tmp_path):
    group = _make_group(tmp_path, "BOLD_rest")
    build_staging([group], tmp_path / "bids")
    assert group.staging_dir is not None


def test_cleanup_removes_staging(tmp_path):
    group = _make_group(tmp_path, "DWI")
    output = tmp_path / "bids"
    build_staging([group], output)
    staging_root = output / ".simpleBIDS_staging"
    assert staging_root.exists()
    cleanup_staging(output)
    assert not staging_root.exists()


# ---------------------------------------------------------------------------
# progress_callback
# ---------------------------------------------------------------------------


def test_build_staging_progress_callback_called(tmp_path: Path) -> None:
    groups = [_make_group(tmp_path, f"series_{i}", n_files=2) for i in range(4)]
    output = tmp_path / "bids"
    calls: list[tuple[int, int]] = []
    build_staging(groups, output, progress_callback=lambda d, t: calls.append((d, t)))

    assert len(calls) == 4
    dones = [d for d, _ in calls]
    assert dones == [1, 2, 3, 4]


def test_build_staging_progress_callback_total_is_correct(tmp_path: Path) -> None:
    n = 3
    groups = [_make_group(tmp_path, f"s{i}") for i in range(n)]
    totals: list[int] = []
    build_staging(
        groups, tmp_path / "bids", progress_callback=lambda d, t: totals.append(t)
    )
    assert all(t == n for t in totals)


def test_build_staging_no_callback_does_not_raise(tmp_path: Path) -> None:
    group = _make_group(tmp_path, "T1w")
    build_staging([group], tmp_path / "bids")  # no callback — must not raise


def test_build_staging_symlinks_point_to_originals(tmp_path: Path) -> None:
    group = _make_group(tmp_path, "T1w", n_files=2)
    build_staging([group], tmp_path / "bids")
    for link in group.staging_dir.iterdir():
        assert link.resolve().exists()


def test_build_staging_idempotent(tmp_path: Path) -> None:
    """Re-running build_staging on the same group should overwrite stale links."""
    group = _make_group(tmp_path, "T1w")
    output = tmp_path / "bids"
    build_staging([group], output)
    first_dir = group.staging_dir
    build_staging([group], output)
    # staging_dir attribute should be updated to same location
    assert group.staging_dir.is_dir()
    assert len(list(group.staging_dir.iterdir())) == 3


def test_cleanup_staging_custom_root(tmp_path: Path) -> None:
    custom_staging = tmp_path / "custom_staging"
    group = _make_group(tmp_path, "T1w")
    build_staging([group], tmp_path / "bids", staging_root=custom_staging)
    assert custom_staging.exists()
    cleanup_staging(tmp_path / "bids", staging_root=custom_staging)
    assert not custom_staging.exists()


def test_build_staging_symlink_failure_does_not_crash(tmp_path: Path) -> None:
    """If symlink_to raises (e.g., permission error), the warning is logged but
    build_staging continues without raising (lines 62-63 in symlink_sorter.py)."""
    from unittest.mock import patch

    group = _make_group(tmp_path, "T1w")
    output = tmp_path / "bids"

    # Patch Path.symlink_to to raise OSError
    with patch("pathlib.Path.symlink_to", side_effect=OSError("permission denied")):
        # Should not raise
        build_staging([group], output)

    # staging_dir is still set even though symlinks failed
    assert group.staging_dir is not None

