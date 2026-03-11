"""Modality/suffix input form populated from the BIDS schema."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from simpleBIDS.bids.config_builder import LabeledSeries
from simpleBIDS.patterns.series_grouper import SeriesGroup

logger = logging.getLogger(__name__)


class LabelForm(ttk.Frame):
    """Right-hand panel for labeling a series with BIDS datatype + suffix.

    Dropdowns are populated from :mod:`simpleBIDS.schema.bids_schema` so they
    always reflect the bundled BIDS specification. Free-text entry is allowed
    as a fallback (with a warning).

    Args:
        parent: Parent widget.
        series_group: The series being labeled.
        on_submit: Callback receiving the completed :class:`LabeledSeries`.
        on_skip: Callback when user skips this series.
        on_back: Callback when user goes back to the previous series.
        current: 1-based index of the current series.
        total: Total number of series to label.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        series_group: SeriesGroup,
        on_submit: Callable[[LabeledSeries], None],
        on_skip: Callable[[], None],
        on_back: Callable[[], None],
        current: int,
        total: int,
    ) -> None:
        super().__init__(parent, relief=tk.GROOVE, borderwidth=1)
        self._group = series_group
        self._on_submit = on_submit
        self._on_skip = on_skip
        self._on_back = on_back
        self._current = current
        self._total = total

        # Schema — gracefully degrade if submodule not initialized
        try:
            from simpleBIDS.schema.bids_schema import get_schema
            self._schema = get_schema()
        except Exception:
            self._schema = None
            logger.warning("BIDS schema unavailable; dropdowns will not be populated")

        self._entity_vars: dict[str, tk.StringVar] = {}
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text=f"Series {self._current} of {self._total}",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(pady=(8, 2))

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=12, pady=4)

        # Datatype
        ttk.Label(form, text="Data type:", anchor=tk.W).grid(row=0, column=0, sticky=tk.W, pady=4)
        self._datatype_var = tk.StringVar(value=self._group.suggested_datatype or "")
        datatypes = self._schema.get_datatypes() if self._schema else []
        self._datatype_cb = ttk.Combobox(form, textvariable=self._datatype_var, values=datatypes, width=20)
        self._datatype_cb.grid(row=0, column=1, sticky=tk.W, padx=4)
        self._datatype_cb.bind("<<ComboboxSelected>>", self._on_datatype_change)

        # Suffix
        ttk.Label(form, text="Suffix:", anchor=tk.W).grid(row=1, column=0, sticky=tk.W, pady=4)
        self._suffix_var = tk.StringVar(value=self._group.suggested_suffix or "")
        self._suffix_cb = ttk.Combobox(form, textvariable=self._suffix_var, values=[], width=20)
        self._suffix_cb.grid(row=1, column=1, sticky=tk.W, padx=4)
        self._suffix_cb.bind("<<ComboboxSelected>>", self._on_suffix_change)

        # Entity fields (rendered dynamically)
        self._entities_frame = ttk.LabelFrame(form, text="Entities")
        self._entities_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=8)

        # Custom criteria
        ttk.Label(form, text="Extra criteria (JSON):", anchor=tk.W).grid(
            row=3, column=0, sticky=tk.NW, pady=4
        )
        self._criteria_text = tk.Text(form, height=3, width=28)
        self._criteria_text.grid(row=3, column=1, sticky=tk.W, padx=4)

        # Apply to all matching
        self._apply_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text='Apply to all series with same description',
            variable=self._apply_all_var,
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=4)

        # Navigation buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=12)
        ttk.Button(btn_frame, text="← Back", command=self._on_back).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Skip", command=self._on_skip).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Next →", command=self._submit).pack(side=tk.LEFT, padx=4)

        # Pre-populate suffix dropdown if a suggested datatype is set
        if self._group.suggested_datatype:
            self._on_datatype_change()

    def _on_datatype_change(self, _event=None) -> None:
        datatype = self._datatype_var.get()
        if self._schema and datatype:
            suffixes = self._schema.get_suffixes(datatype)
            self._suffix_cb["values"] = suffixes
        self._on_suffix_change()

    def _on_suffix_change(self, _event=None) -> None:
        datatype = self._datatype_var.get()
        suffix = self._suffix_var.get()
        self._render_entity_fields(datatype, suffix)

    def _render_entity_fields(self, datatype: str, suffix: str) -> None:
        for widget in self._entities_frame.winfo_children():
            widget.destroy()
        self._entity_vars.clear()

        if not self._schema or not datatype or not suffix:
            return

        required = self._schema.get_required_entities(datatype, suffix)
        all_entities = self._schema.get_entities(datatype, suffix)

        # Always exclude sub/ses — those come from inference
        skip = {"subject", "session", "sub", "ses"}
        entities_to_show = [e for e in all_entities if e not in skip]

        for row_idx, entity in enumerate(entities_to_show):
            is_required = entity in required
            label_text = f"{entity}{'*' if is_required else ''} :"
            ttk.Label(self._entities_frame, text=label_text, width=14, anchor=tk.W).grid(
                row=row_idx, column=0, sticky=tk.W, padx=4, pady=2
            )
            var = tk.StringVar()
            self._entity_vars[entity] = var
            ttk.Entry(self._entities_frame, textvariable=var, width=18).grid(
                row=row_idx, column=1, sticky=tk.W, padx=4, pady=2
            )

    def _submit(self) -> None:
        datatype = self._datatype_var.get().strip()
        suffix = self._suffix_var.get().strip()

        if not datatype or not suffix:
            messagebox.showwarning("Incomplete", "Please select a data type and suffix.")
            return

        # Warn if suffix is non-standard
        if self._schema and not self._schema.validate_suffix(datatype, suffix):
            ok = messagebox.askyesno(
                "Non-standard suffix",
                f"'{suffix}' is not a standard BIDS suffix for '{datatype}'.\n"
                "This may fail BIDS validation. Continue anyway?",
            )
            if not ok:
                return

        entities = {k: v.get().strip() for k, v in self._entity_vars.items() if v.get().strip()}

        # Parse optional custom criteria JSON
        custom_criteria: dict = {}
        raw = self._criteria_text.get("1.0", tk.END).strip()
        if raw:
            import json
            try:
                custom_criteria = json.loads(raw)
            except json.JSONDecodeError:
                messagebox.showerror("JSON error", "Extra criteria is not valid JSON.")
                return

        labeled = LabeledSeries(
            series_group=self._group,
            datatype=datatype,
            suffix=suffix,
            entities=entities,
            custom_criteria=custom_criteria,
        )
        self._on_submit(labeled)
