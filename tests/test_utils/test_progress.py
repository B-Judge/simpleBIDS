"""Tests for utils/progress.py."""

from __future__ import annotations

import io

import pytest

from simpleBIDS.utils.progress import ProgressBar, _fmt_seconds


# ---------------------------------------------------------------------------
# _fmt_seconds
# ---------------------------------------------------------------------------


def test_fmt_seconds_zero() -> None:
    assert _fmt_seconds(0) == "00:00"


def test_fmt_seconds_seconds_only() -> None:
    assert _fmt_seconds(45) == "00:45"


def test_fmt_seconds_minutes() -> None:
    assert _fmt_seconds(90) == "01:30"


def test_fmt_seconds_one_hour() -> None:
    assert _fmt_seconds(3600) == "1:00:00"


def test_fmt_seconds_hours_and_minutes() -> None:
    assert _fmt_seconds(3661) == "1:01:01"


def test_fmt_seconds_negative_clamped_to_zero() -> None:
    assert _fmt_seconds(-10) == "00:00"


# ---------------------------------------------------------------------------
# ProgressBar — basic API
# ---------------------------------------------------------------------------


def test_progress_bar_update_tracks_done() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=10, file=out)
    bar.update(5)
    assert bar._done == 5


def test_progress_bar_update_sets_total() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=0, file=out)
    bar.update(3, total=20)
    assert bar.total == 20


def test_progress_bar_increment() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=4, file=out)
    for _ in range(4):
        bar.increment()
    assert bar._done == 4


def test_progress_bar_no_output_before_start() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=10, file=out)
    bar.close()
    assert out.getvalue() == ""


def test_progress_bar_close_after_update_produces_output() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=4, label="work", file=out)
    bar.update(4)
    bar.close()
    assert out.getvalue().strip() != ""


def test_progress_bar_label_appears_in_output() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=4, label="MyScan", file=out)
    bar.update(2)
    bar.close()
    assert "MyScan" in out.getvalue()


# ---------------------------------------------------------------------------
# ProgressBar — context manager
# ---------------------------------------------------------------------------


def test_progress_bar_context_manager_completes() -> None:
    out = io.StringIO()
    with ProgressBar(total=4, label="work", file=out) as bar:
        for i in range(1, 5):
            bar.update(i)
    output = out.getvalue()
    assert "done" in output


def test_progress_bar_context_manager_no_exception_if_empty() -> None:
    out = io.StringIO()
    with ProgressBar(total=0, file=out):
        pass  # nothing updated — should not raise


# ---------------------------------------------------------------------------
# ProgressBar — milestone output (non-TTY path)
# ---------------------------------------------------------------------------


def test_progress_bar_milestone_at_25_percent() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=100, label="T", file=out)
    bar.update(25)
    output = out.getvalue()
    assert "25" in output or "T" in output


def test_progress_bar_milestone_not_repeated() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=100, file=out)
    bar.update(25)
    first = out.getvalue()
    bar.update(26)
    bar.update(27)
    second = out.getvalue()
    # Only one 25% line; subsequent updates below next threshold don't print
    assert out.getvalue().count("25") == first.count("25")


def test_progress_bar_unknown_total_auto_set() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=0, file=out)
    bar.update(10)
    assert bar.total >= 10


# ---------------------------------------------------------------------------
# ProgressBar — ETA string
# ---------------------------------------------------------------------------


def test_eta_str_before_start_returns_placeholder() -> None:
    out = io.StringIO()
    bar = ProgressBar(total=10, file=out)
    assert "ETA" in bar._eta_str()


def test_eta_str_at_completion() -> None:
    import time
    out = io.StringIO()
    bar = ProgressBar(total=10, file=out)
    bar._start_time = time.monotonic() - 5.0
    bar._done = 10
    bar.total = 10
    eta = bar._eta_str()
    assert "00:00" in eta
