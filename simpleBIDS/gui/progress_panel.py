"""Progress display panel for scanning and conversion steps."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ProgressPanel(ttk.Frame):
    """Scrollable log panel with an indeterminate progress bar.

    Args:
        parent: Parent widget.
        title: Heading text shown above the log.
    """

    def __init__(self, parent: tk.Widget, *, title: str = "Working…") -> None:
        super().__init__(parent)
        self._build(title)

    def _build(self, title: str) -> None:
        ttk.Label(self, text=title, font=("TkDefaultFont", 11, "bold")).pack(pady=(12, 4))

        self._progress = ttk.Progressbar(self, mode="indeterminate", length=400)
        self._progress.pack(pady=4)
        self._progress.start(10)

        log_frame = ttk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._log_box = tk.Text(
            log_frame,
            state=tk.DISABLED,
            yscrollcommand=scrollbar.set,
            wrap=tk.WORD,
            font=("TkFixedFont", 9),
        )
        self._log_box.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._log_box.yview)

    def log(self, message: str) -> None:
        """Append *message* to the log box (thread-safe via ``after``)."""
        self._log_box.config(state=tk.NORMAL)
        self._log_box.insert(tk.END, message + "\n")
        self._log_box.see(tk.END)
        self._log_box.config(state=tk.DISABLED)

    def done(self) -> None:
        """Stop the progress bar animation."""
        self._progress.stop()
