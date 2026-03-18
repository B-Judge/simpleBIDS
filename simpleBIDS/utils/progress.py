"""Minimal terminal progress bar — stdlib only, no external dependencies."""

from __future__ import annotations

import sys
import time
from typing import TextIO


def _fmt_seconds(secs: float) -> str:
    """Format a duration in seconds as MM:SS (or H:MM:SS for >= 1 hour)."""
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ProgressBar:
    """Single-line terminal progress bar.

    Writes to stdout using ``\\r`` to update in place on TTY.  On non-TTY
    streams (pipes, redirected output) it prints milestone updates at
    0 %, 25 %, 50 %, 75 %, and 100 % instead.

    Usage as a context manager::

        with ProgressBar(total=100, label="Scanning files") as bar:
            for i, item in enumerate(items, 1):
                process(item)
                bar.update(i, total)
        # bar prints a final "done" line on exit

    Usage with a callback (matching the ``progress_callback(done, total)``
    signature used by the DICOM scanner)::

        bar = ProgressBar(label="Reading files")
        group_series(root, progress_callback=bar.update)
        bar.close()

    Args:
        total: Expected number of steps.  May be 0 if unknown; the first
            :meth:`update` call will set the real total.
        label: Short text prefix printed before the bar.
        width: Width of the filled/empty bar segment in characters.
        file: Output stream (default ``sys.stdout``).
    """

    _BAR_FULL = "█"
    _BAR_EMPTY = "░"

    def __init__(
        self,
        total: int = 0,
        label: str = "",
        width: int = 36,
        file: TextIO | None = None,
    ) -> None:
        self.total = max(total, 1) if total > 0 else 0
        self.label = label
        self.width = width
        self._file = file or sys.stdout
        self._done = 0
        self._tty = getattr(self._file, "isatty", lambda: False)()
        self._last_milestone = -1
        self._started = False
        self._start_time: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, done: int, total: int | None = None) -> None:
        """Update progress to *done* out of *total* steps.

        Args:
            done: Number of steps completed so far.
            total: Total steps (updates the stored total if provided).
        """
        if self._start_time is None:
            self._start_time = time.monotonic()
        self._done = done
        if total is not None and total > 0:
            self.total = total
        if self.total == 0:
            self.total = max(done, 1)
        self._started = True

        if self._tty:
            self._render_tty()
        else:
            self._render_milestone()

    def increment(self) -> None:
        """Advance by one step."""
        self.update(self._done + 1)

    def close(self) -> None:
        """Print a final completion line and move to the next line."""
        if not self._started:
            return
        elapsed = time.monotonic() - (self._start_time or time.monotonic())
        elapsed_str = _fmt_seconds(elapsed)
        label_prefix = f"{self.label}: " if self.label else ""
        if self._tty:
            filled = self.width
            bar = self._BAR_FULL * filled
            line = (
                f"\r{label_prefix}[{bar}] 100%  "
                f"{self._done}/{self._done}  done in {elapsed_str}"
            )
            print(line, file=self._file, flush=True)
        else:
            print(
                f"{label_prefix}done ({self._done}/{self._done})  [{elapsed_str}]",
                file=self._file,
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ProgressBar":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal rendering
    # ------------------------------------------------------------------

    def _render_tty(self) -> None:
        pct = self._done / self.total
        filled = int(self.width * pct)
        bar = self._BAR_FULL * filled + self._BAR_EMPTY * (self.width - filled)
        label_prefix = f"{self.label}: " if self.label else ""
        eta_str = self._eta_str()
        line = (
            f"\r{label_prefix}[{bar}] {pct:5.1%}  "
            f"{self._done}/{self.total}  {eta_str}"
        )
        print(line, end="", file=self._file, flush=True)

    def _render_milestone(self) -> None:
        pct = int(100 * self._done / self.total)
        milestone = (pct // 25) * 25
        if milestone > self._last_milestone:
            self._last_milestone = milestone
            label_prefix = f"{self.label}: " if self.label else ""
            eta_str = self._eta_str()
            print(
                f"{label_prefix}{self._done}/{self.total} ({pct}%)  {eta_str}",
                file=self._file,
            )

    def _eta_str(self) -> str:
        """Return a human-readable ETA string, or 'ETA --:--' if unavailable."""
        if self._start_time is None or self._done == 0:
            return "ETA --:--"
        elapsed = time.monotonic() - self._start_time
        rate = self._done / elapsed  # items per second
        remaining = self.total - self._done
        if rate <= 0 or remaining <= 0:
            return "ETA 00:00"
        eta_secs = remaining / rate
        return f"ETA {_fmt_seconds(eta_secs)}"
