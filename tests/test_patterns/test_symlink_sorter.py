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
