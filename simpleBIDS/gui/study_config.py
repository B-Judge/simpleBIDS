"""Study-level configuration panel: review inferred subjects and sessions."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from simpleBIDS.patterns.series_grouper import SeriesGroup


class StudyConfigPanel(ttk.Frame):
    """Display and allow editing of inferred subject/session identifiers.

    Shows a summary table of all subjects × sessions found in the dataset.
    The user can override any inferred value before proceeding to series labeling.

    Args:
        parent: Parent widget.
        series_groups: All series groups (modified in place on confirm).
        on_confirm: Callback invoked when the user accepts the configuration.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        series_groups: list[SeriesGroup],
        on_confirm: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._groups = series_groups
        self._on_confirm = on_confirm
        self._row_vars: list[tuple[tk.StringVar, tk.StringVar]] = []  # (subject_var, session_var)
        self._build()

    def _build(self) -> None:
        ttk.Label(self, text="Review Subjects & Sessions", font=("TkDefaultFont", 12, "bold")).pack(
            pady=(12, 4)
        )
        ttk.Label(
            self,
            text="Edit any inferred values below. Changes apply to all series with that value.",
            wraplength=700,
        ).pack(pady=(0, 8))

        # Deduplicate to unique (subject, session) pairs
        seen: dict[tuple[str | None, str | None], int] = {}
        for g in self._groups:
            key = (g.subject_id, g.session_id)
            seen[key] = seen.get(key, 0) + 1

        # Table
        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12)

        headers = ["Subject ID (inferred)", "Session ID (inferred)", "Series count"]
        for col, text in enumerate(headers):
            ttk.Label(table_frame, text=text, font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=col, padx=8, pady=4, sticky=tk.W
            )

        self._pair_vars: list[tuple[str | None, str | None, tk.StringVar, tk.StringVar]] = []

        for row_idx, ((subj, sess), count) in enumerate(sorted(seen.items()), start=1):
            subj_var = tk.StringVar(value=subj or "")
            sess_var = tk.StringVar(value=sess or "")
            self._pair_vars.append((subj, sess, subj_var, sess_var))

            ttk.Entry(table_frame, textvariable=subj_var, width=20).grid(
                row=row_idx, column=0, padx=8, pady=2
            )
            ttk.Entry(table_frame, textvariable=sess_var, width=20).grid(
                row=row_idx, column=1, padx=8, pady=2
            )
            ttk.Label(table_frame, text=str(count)).grid(
                row=row_idx, column=2, padx=8, pady=2
            )

        ttk.Button(self, text="Confirm & Label Series →", command=self._confirm).pack(pady=16)

    def _confirm(self) -> None:
        # Apply any edits back to all matching series groups
        for orig_subj, orig_sess, subj_var, sess_var in self._pair_vars:
            new_subj = subj_var.get().strip() or None
            new_sess = sess_var.get().strip() or None
            for group in self._groups:
                if group.subject_id == orig_subj and group.session_id == orig_sess:
                    group.subject_id = new_subj
                    group.session_id = new_sess

        self._on_confirm()
