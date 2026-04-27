"""Panel that displays a representative image slice and series metadata."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from simpleBIDS.patterns.series_grouper import SeriesGroup

logger = logging.getLogger(__name__)


class SeriesPanel(ttk.Frame):
    """Left-hand panel showing the image and series description.

    Args:
        parent: Parent widget.
        series_group: The series to display.
        log_dir: Optional directory where a copy of the displayed PNG is saved
            as a paper trail of what the user saw during labeling.
    """

    _IMAGE_SIZE = (320, 320)

    def __init__(
        self,
        parent: tk.Widget,
        *,
        series_group: SeriesGroup,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(parent, relief=tk.GROOVE, borderwidth=1)
        self._group = series_group
        self._log_dir = log_dir
        self._photo: tk.PhotoImage | None = None  # keep reference to avoid GC

        self._build()
        self._load_image()

    def _build(self) -> None:
        ttk.Label(self, text="Preview", font=("TkDefaultFont", 10, "bold")).pack(pady=(8, 4))

        self._canvas = tk.Canvas(self, width=self._IMAGE_SIZE[0], height=self._IMAGE_SIZE[1], bg="black")
        self._canvas.pack(padx=8, pady=4)

        info_frame = ttk.Frame(self)
        info_frame.pack(fill=tk.X, padx=8, pady=8)

        self._add_row(info_frame, "Series description", self._group.series_description or "—")
        self._add_row(info_frame, "Series number", str(self._group.series_number or "—"))
        self._add_row(info_frame, "Modality", self._group.modality or "—")
        self._add_row(info_frame, "Files", str(self._group.file_count))
        self._add_row(info_frame, "Subject (inferred)", self._group.subject_id or "—")
        self._add_row(info_frame, "Session (inferred)", self._group.session_id or "—")

    def _add_row(self, parent: tk.Widget, label: str, value: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=1)
        ttk.Label(row, text=f"{label}:", width=22, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(row, text=value, anchor=tk.W, wraplength=280).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _load_image(self) -> None:
        """Load and display the representative image slice asynchronously."""
        try:
            from PIL import Image, ImageTk
            import numpy as np
            from simpleBIDS.patterns.slice_sampler import sample_slice

            arr = sample_slice(self._group.representative_file)
            img = Image.fromarray(arr, mode="L").resize(self._IMAGE_SIZE, Image.LANCZOS)

            # Save a copy to the logging directory as a paper trail.
            if self._log_dir is not None:
                try:
                    self._log_dir.mkdir(parents=True, exist_ok=True)
                    img.save(self._log_dir / f"{self._group.slug}.png")
                except Exception as save_exc:
                    logger.debug("Could not save slice preview to log_dir: %s", save_exc)

            self._photo = ImageTk.PhotoImage(img)
            self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        except Exception as exc:
            logger.debug("Could not load image for %s: %s", self._group.representative_file, exc)
            self._canvas.create_text(
                self._IMAGE_SIZE[0] // 2,
                self._IMAGE_SIZE[1] // 2,
                text="Preview unavailable",
                fill="gray",
            )
