"""Pre-labeling series filter panel.

Presents a scrollable checkbox list so the user can exclude unwanted series
(e.g. localizer/scout scans) before the main labeling loop.  Localizer
series are pre-checked for exclusion; the user can adjust freely.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable

from simpleBIDS.cli.label import get_default_excluded_indices
from simpleBIDS.patterns.series_grouper import SeriesGroup

logger = logging.getLogger(__name__)


class SeriesFilterPanel(ttk.Frame):
    """Pre-labeling filter screen — scrollable checkbox list of all series.

    Localizer/scout series are pre-checked (marked for exclusion).  The user
    may uncheck any to include them in labeling, or check non-localizers to
    skip them.

    Args:
        parent: Parent widget.
        series_groups: All series from the scan.
        on_confirm: Callback receiving the subset of series the user chose
            to keep for labeling (i.e. the *unchecked* ones).
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        series_groups: list[SeriesGroup],
        on_confirm: Callable[[list[SeriesGroup]], None],
    ) -> None:
        super().__init__(parent)
        self._groups = series_groups
        self._on_confirm = on_confirm
        self._vars: list[tk.BooleanVar] = []
        self._build()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        ttk.Label(
            self,
            text="Review Series",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(pady=(12, 4))

        ttk.Label(
            self,
            text=(
                "Checked series will be excluded from the labeling step.\n"
                "Localizer/scout scans are pre-checked.  Adjust as needed."
            ),
            justify=tk.CENTER,
        ).pack(pady=(0, 4))

        n_total = len(self._groups)
        n_loc = sum(1 for g in self._groups if g.is_localizer)
        ttk.Label(
            self,
            text=(
                f"{n_total} series total  |  "
                f"{n_loc} localizer/scout pre-selected for exclusion"
            ),
            foreground="gray",
        ).pack(pady=(0, 8))

        # Scrollable list
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=12)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Column headers
        hdr = ttk.Frame(inner)
        hdr.pack(fill=tk.X, padx=4, pady=(0, 2))
        ttk.Label(hdr, text="Exclude", width=8, anchor=tk.CENTER).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Series description", width=44, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Mod", width=6, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(hdr, text="Files", width=6, anchor=tk.E).pack(side=tk.LEFT)
        ttk.Separator(inner, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=4, pady=(0, 2))

        excluded_by_default = set(get_default_excluded_indices(self._groups))
        for i, group in enumerate(self._groups):
            var = tk.BooleanVar(value=(i in excluded_by_default))
            self._vars.append(var)

            row = ttk.Frame(inner)
            row.pack(fill=tk.X, padx=4, pady=1)

            ttk.Checkbutton(row, variable=var, width=6).pack(side=tk.LEFT)

            desc = group.series_description or "—"
            tag = "  [localizer/scout]" if group.is_localizer else ""
            ttk.Label(
                row, text=(desc + tag)[:52], width=44, anchor=tk.W
            ).pack(side=tk.LEFT)
            ttk.Label(row, text=group.modality or "—", width=6, anchor=tk.W).pack(
                side=tk.LEFT
            )
            ttk.Label(row, text=str(group.file_count), width=6, anchor=tk.E).pack(
                side=tk.LEFT
            )

        # Bottom buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=12)
        ttk.Button(
            btn_frame, text="Check All", command=self._check_all
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame, text="Uncheck All", command=self._uncheck_all
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_frame,
            text="Proceed to Labeling →",
            command=self._proceed,
        ).pack(side=tk.LEFT, padx=16)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _check_all(self) -> None:
        for var in self._vars:
            var.set(True)

    def _uncheck_all(self) -> None:
        for var in self._vars:
            var.set(False)

    def _proceed(self) -> None:
        excluded = self.get_excluded_indices()
        excluded_set = set(excluded)
        filtered = [g for i, g in enumerate(self._groups) if i not in excluded_set]
        logger.info(
            "Series filter: keeping %d of %d series (%d excluded)",
            len(filtered), len(self._groups), len(excluded),
        )
        self._on_confirm(filtered)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_excluded_indices(self) -> list[int]:
        """Return the indices (into the original group list) that are checked."""
        return [i for i, var in enumerate(self._vars) if var.get()]
