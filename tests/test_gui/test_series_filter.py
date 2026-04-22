"""Tests for gui/series_filter.py — headless logic tests (no display required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from simpleBIDS.cli.label import get_default_excluded_indices
from simpleBIDS.patterns.series_grouper import SeriesGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_group(
    description: str,
    *,
    is_localizer: bool = False,
    file_count: int = 10,
) -> SeriesGroup:
    return SeriesGroup(
        series_description=description,
        series_number=1,
        modality="MR",
        all_files=[],
        representative_file=Path("/fake/file.dcm"),
        file_count=file_count,
        is_localizer=is_localizer,
    )


# ---------------------------------------------------------------------------
# get_default_excluded_indices
# ---------------------------------------------------------------------------


def test_default_excludes_localizer_series() -> None:
    groups = [
        _make_group("AAHeadScout", is_localizer=True),
        _make_group("T1w_MPRAGE", is_localizer=False),
        _make_group("BOLD_rest", is_localizer=False),
    ]
    excluded = get_default_excluded_indices(groups)
    assert excluded == [0]


def test_default_excludes_multiple_localizers() -> None:
    groups = [
        _make_group("AAScout", is_localizer=True),
        _make_group("T1w_MPRAGE"),
        _make_group("LocalizerCoronal", is_localizer=True),
        _make_group("BOLD_rest"),
    ]
    excluded = get_default_excluded_indices(groups)
    assert excluded == [0, 2]


def test_default_excludes_nothing_when_no_localizers() -> None:
    groups = [
        _make_group("T1w_MPRAGE"),
        _make_group("BOLD_rest"),
        _make_group("DWI_b1000"),
    ]
    excluded = get_default_excluded_indices(groups)
    assert excluded == []


def test_default_excludes_all_when_all_localizers() -> None:
    groups = [
        _make_group("Scout1", is_localizer=True),
        _make_group("Scout2", is_localizer=True),
    ]
    excluded = get_default_excluded_indices(groups)
    assert excluded == [0, 1]


def test_default_excludes_empty_list() -> None:
    assert get_default_excluded_indices([]) == []


# ---------------------------------------------------------------------------
# Filter logic (simulated proceed without tkinter)
# ---------------------------------------------------------------------------


def _apply_filter(groups: list[SeriesGroup], excluded_indices: list[int]) -> list[SeriesGroup]:
    """Reproduce what SeriesFilterPanel._proceed does, without a display."""
    excluded = set(excluded_indices)
    return [g for i, g in enumerate(groups) if i not in excluded]


def test_filter_removes_excluded_series() -> None:
    groups = [
        _make_group("AAHeadScout", is_localizer=True),
        _make_group("T1w_MPRAGE"),
        _make_group("BOLD_rest"),
    ]
    excluded = get_default_excluded_indices(groups)
    filtered = _apply_filter(groups, excluded)
    assert len(filtered) == 2
    descs = [g.series_description for g in filtered]
    assert "AAHeadScout" not in descs
    assert "T1w_MPRAGE" in descs
    assert "BOLD_rest" in descs


def test_filter_empty_exclusion_returns_all() -> None:
    groups = [_make_group("T1w"), _make_group("BOLD")]
    filtered = _apply_filter(groups, [])
    assert filtered == groups


def test_filter_all_excluded_returns_empty() -> None:
    groups = [_make_group("T1w"), _make_group("BOLD")]
    filtered = _apply_filter(groups, [0, 1])
    assert filtered == []


def test_filter_preserves_group_identity() -> None:
    """The returned groups are the exact same objects, not copies."""
    groups = [_make_group("T1w"), _make_group("BOLD"), _make_group("DWI")]
    filtered = _apply_filter(groups, [1])
    assert filtered[0] is groups[0]
    assert filtered[1] is groups[2]
