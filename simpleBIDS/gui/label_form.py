"""Modality/suffix input form populated from the BIDS schema."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from simpleBIDS.bids.config_builder import LabeledSeries
from simpleBIDS.cli.label import BIDS_OPTIONAL_ENTITIES
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
        self._optional_entity_vars: dict[str, tk.StringVar] = {}
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

        # Entity fields (rendered dynamically from schema)
        self._entities_frame = ttk.LabelFrame(form, text="Entities")
        self._entities_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=4)

        # Optional BIDS labels — always visible, common entities not always in schema
        self._optional_frame = ttk.LabelFrame(form, text="Optional BIDS Labels")
        self._optional_frame.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=4)
        self._build_optional_entity_fields()

        # Custom criteria
        ttk.Label(form, text="Extra criteria (JSON):", anchor=tk.W).grid(
            row=4, column=0, sticky=tk.NW, pady=4
        )
        self._criteria_text = tk.Text(form, height=3, width=28)
        self._criteria_text.grid(row=4, column=1, sticky=tk.W, padx=4)

        # Navigation buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=12)
        ttk.Button(btn_frame, text="← Back", command=self._on_back).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Skip", command=self._on_skip).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Next →", command=self._submit).pack(side=tk.LEFT, padx=4)

        # Pre-populate suffix dropdown if a suggested datatype is set
        if self._group.suggested_datatype:
            self._on_datatype_change()

    # All standard BIDS entities exposed as optional inputs.
    # Defined in cli/label.py so non-GUI code and tests can import without tkinter.
    # Entities already shown in the schema-driven section are filtered out at
    # build time; sub and ses are never included (they are inferred).
    _OPTIONAL_ENTITIES = BIDS_OPTIONAL_ENTITIES

    def _build_optional_entity_fields(self) -> None:
        """Populate the Optional BIDS Labels section.

        Entities already shown in the schema-driven section are omitted to
        avoid duplication.  Called once at build time and again whenever the
        schema section is rebuilt (datatype/suffix change).
        """
        for widget in self._optional_frame.winfo_children():
            widget.destroy()
        self._optional_entity_vars.clear()

        already_shown = set(self._entity_vars.keys())
        row_idx = 0
        for entity_key, display_label in self._OPTIONAL_ENTITIES:
            if entity_key in already_shown:
                continue
            var = tk.StringVar()
            self._optional_entity_vars[entity_key] = var
            ttk.Label(
                self._optional_frame,
                text=display_label,
                width=26,
                anchor=tk.W,
            ).grid(row=row_idx, column=0, sticky=tk.W, padx=4, pady=2)
            ttk.Entry(
                self._optional_frame, textvariable=var, width=18
            ).grid(row=row_idx, column=1, sticky=tk.W, padx=4, pady=2)
            row_idx += 1

        if row_idx == 0:
            ttk.Label(
                self._optional_frame,
                text="(all optional labels are covered by the Entities section above)",
                foreground="gray",
            ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=4, pady=2)

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
            # Rebuild optional section with no schema entities present
            self._build_optional_entity_fields()
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

        # Rebuild optional section to exclude any entities now in schema section
        self._build_optional_entity_fields()

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

        # Merge schema-driven entities and manually entered optional labels
        entities = {k: v.get().strip() for k, v in self._entity_vars.items() if v.get().strip()}
        for k, v in self._optional_entity_vars.items():
            val = v.get().strip()
            if val:
                entities[k] = val

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
