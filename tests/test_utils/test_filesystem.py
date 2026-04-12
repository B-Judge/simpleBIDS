"""Tests for utils/filesystem.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from simpleBIDS.utils.filesystem import ensure_dir, iter_files, safe_stem


# ---------------------------------------------------------------------------
# iter_files
# ---------------------------------------------------------------------------


def test_iter_files_yields_all(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    files = list(iter_files(tmp_path))
    assert len(files) == 2


def test_iter_files_suffix_filter(tmp_path: Path) -> None:
    (tmp_path / "scan.dcm").write_text("dcm")
    (tmp_path / "image.nii").write_text("nii")
    (tmp_path / "readme.txt").write_text("txt")
    files = list(iter_files(tmp_path, suffixes={".dcm"}))
    assert len(files) == 1
    assert files[0].suffix == ".dcm"


def test_iter_files_multiple_suffix_filter(tmp_path: Path) -> None:
    (tmp_path / "a.dcm").write_text("x")
    (tmp_path / "b.nii").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    files = list(iter_files(tmp_path, suffixes={".dcm", ".nii"}))
    assert len(files) == 2


def test_iter_files_limit(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"{i}.txt").write_text(str(i))
    files = list(iter_files(tmp_path, limit=3))
    assert len(files) == 3


def test_iter_files_limit_larger_than_count(tmp_path: Path) -> None:
    (tmp_path / "only.txt").write_text("x")
    files = list(iter_files(tmp_path, limit=100))
    assert len(files) == 1


def test_iter_files_recursive(tmp_path: Path) -> None:
    sub = tmp_path / "sub" / "nested"
    sub.mkdir(parents=True)
    (sub / "deep.txt").write_text("deep")
    (tmp_path / "top.txt").write_text("top")
    files = list(iter_files(tmp_path))
    assert len(files) == 2


def test_iter_files_empty_dir(tmp_path: Path) -> None:
    assert list(iter_files(tmp_path)) == []


def test_iter_files_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    (tmp_path / "file.txt").write_text("x")
    files = list(iter_files(tmp_path))
    assert len(files) == 1
    assert files[0].name == "file.txt"


def test_iter_files_suffix_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "A.DCM").write_text("x")
    (tmp_path / "b.dcm").write_text("x")
    files = list(iter_files(tmp_path, suffixes={".dcm"}))
    assert len(files) == 2


# ---------------------------------------------------------------------------
# ensure_dir
# ---------------------------------------------------------------------------


def test_ensure_dir_creates_nested(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "dir"
    result = ensure_dir(target)
    assert target.is_dir()
    assert result == target


def test_ensure_dir_returns_path(tmp_path: Path) -> None:
    target = tmp_path / "new"
    assert ensure_dir(target) is target


def test_ensure_dir_idempotent(tmp_path: Path) -> None:
    ensure_dir(tmp_path)  # already exists — must not raise
    assert tmp_path.is_dir()


def test_ensure_dir_existing_dir(tmp_path: Path) -> None:
    sub = tmp_path / "exists"
    sub.mkdir()
    ensure_dir(sub)  # should not raise
    assert sub.is_dir()


# ---------------------------------------------------------------------------
# safe_stem
# ---------------------------------------------------------------------------


def test_safe_stem_replaces_spaces() -> None:
    assert safe_stem("hello world") == "hello_world"


def test_safe_stem_removes_special_chars() -> None:
    result = safe_stem("T2* / FLAIR!")
    assert all(c.isalnum() or c in "-_." for c in result)


def test_safe_stem_preserves_alnum() -> None:
    assert safe_stem("T1w001") == "T1w001"


def test_safe_stem_preserves_hyphen_and_dot() -> None:
    assert safe_stem("sub-01.nii") == "sub-01.nii"


def test_safe_stem_empty_string() -> None:
    assert safe_stem("") == ""


def test_safe_stem_all_special_chars() -> None:
    result = safe_stem("@#$%^&*")
    assert all(c == "_" for c in result)
