"""Main tkinter application entry point."""

from __future__ import annotations

import json
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from simpleBIDS.bids.config_builder import LabeledSeries, build_config, write_config
from simpleBIDS.bids.converter import convert_subject
from simpleBIDS.bids.scaffold import scaffold_bids
from simpleBIDS.inference import infer_session, infer_subject
from simpleBIDS.patterns import build_staging, cleanup_staging, group_series
from simpleBIDS.utils.logging import configure_logging

logger = logging.getLogger(__name__)

# Session cache lives in the standard CLI cache directory so that the App and
# the CLI tools share the same file layout and can interoperate.
_CACHE_DIRNAME = ".simpleBIDS_cache"
_MANIFEST_NAME = "series_manifest.json"
_SESSION_NAME = "app_session.json"


class App(tk.Tk):
    """Main simpleBIDS application window.

    Workflow steps (each implemented as a separate frame/panel):
        1. Directory selection (input raw data, output BIDS root)
        2. Scanning and grouping (with progress)
        3. Subject/session review (``StudyConfigPanel``)
        4. Series labeling loop (``SeriesPanel`` + ``LabelForm``)
        5. Conversion with live progress (``ProgressPanel``)

    Session state is persisted to
    ``<output>/.simpleBIDS_cache/app_session.json`` after every labeling
    decision.  On resume the manifest is read from the same cache directory
    used by the CLI tools, avoiding a full re-scan.
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("simpleBIDS")
        self.resizable(True, True)
        self.minsize(800, 600)

        self._input_dir: Path | None = None
        self._output_dir: Path | None = None
        self._series_groups = []
        self._labeled_series: list[LabeledSeries] = []
        self._label_index: int = 0

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._content = ttk.Frame(self)
        self._content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._show_directory_selector()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, relief=tk.RIDGE)
        bar.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(bar, text="simpleBIDS", font=("TkDefaultFont", 12, "bold")).pack(
            side=tk.LEFT, padx=8, pady=4
        )

    # ------------------------------------------------------------------
    # Step 1 — Directory selection
    # ------------------------------------------------------------------

    def _show_directory_selector(self) -> None:
        self._clear_content()
        frame = ttk.Frame(self._content)
        frame.pack(expand=True)

        ttk.Label(frame, text="Input directory (raw neuroimaging data):").grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        self._input_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._input_var, width=50).grid(row=0, column=1, padx=4)
        ttk.Button(frame, text="Browse…", command=self._browse_input).grid(row=0, column=2)

        ttk.Label(frame, text="Output directory (BIDS root):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self._output_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._output_var, width=50).grid(row=1, column=1, padx=4)
        ttk.Button(frame, text="Browse…", command=self._browse_output).grid(row=1, column=2)

        ttk.Button(frame, text="Scan →", command=self._start_scan).grid(
            row=2, column=1, pady=12
        )

    def _browse_input(self) -> None:
        d = filedialog.askdirectory(title="Select raw data directory")
        if d:
            self._input_var.set(d)

    def _browse_output(self) -> None:
        d = filedialog.askdirectory(title="Select BIDS output directory")
        if d:
            self._output_var.set(d)

    # ------------------------------------------------------------------
    # Step 2 — Scan and group
    # ------------------------------------------------------------------

    def _start_scan(self) -> None:
        input_str = self._input_var.get().strip()
        output_str = self._output_var.get().strip()

        if not input_str or not output_str:
            messagebox.showerror("Missing paths", "Please select both input and output directories.")
            return

        self._input_dir = Path(input_str)
        self._output_dir = Path(output_str)

        if not self._input_dir.is_dir():
            messagebox.showerror("Not a directory", f"{self._input_dir} does not exist.")
            return

        # Check for an existing session in the cache directory
        session_path = self._output_dir / _CACHE_DIRNAME / _SESSION_NAME
        if session_path.exists():
            resume = messagebox.askyesno(
                "Resume session",
                "A previous session was found. Resume from where you left off?",
            )
            if resume:
                self._load_cache(session_path)
                return

        self._clear_content()
        from simpleBIDS.gui.progress_panel import ProgressPanel
        panel = ProgressPanel(self._content, title="Scanning…")
        panel.pack(fill=tk.BOTH, expand=True)

        # Run grouping in a background thread to keep UI responsive
        import threading
        thread = threading.Thread(target=self._do_scan, args=(panel,), daemon=True)
        thread.start()

    def _do_scan(self, panel) -> None:
        try:
            panel.log("Scanning for imaging series…")
            self._series_groups = group_series(self._input_dir)
            panel.log(f"Found {len(self._series_groups)} series.")

            panel.log("Inferring subject/session identifiers…")
            for group in self._series_groups:
                # Use already-parsed DICOM metadata stored in extra rather than
                # re-reading the file; falls back gracefully for NIfTI groups.
                meta = group.extra.get("dicom_metadata")
                group.subject_id = infer_subject(meta, group.representative_file)
                group.session_id = infer_session(meta, group.representative_file)

            panel.log("Building staging directories…")
            build_staging(self._series_groups, self._output_dir)
            panel.log("Staging complete.")

            # Persist the manifest to the CLI-compatible cache directory so
            # the App and CLI tools share the same serialised scan results.
            self._save_manifest()

            self.after(0, self._show_study_config)
        except Exception as exc:
            logger.exception("Scan failed")
            self.after(0, lambda: messagebox.showerror("Scan failed", str(exc)))

    # ------------------------------------------------------------------
    # Step 3 — Study config review
    # ------------------------------------------------------------------

    def _show_study_config(self) -> None:
        self._clear_content()
        from simpleBIDS.gui.study_config import StudyConfigPanel
        panel = StudyConfigPanel(
            self._content,
            series_groups=self._series_groups,
            on_confirm=self._start_labeling,
        )
        panel.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Step 4 — Series labeling
    # ------------------------------------------------------------------

    def _start_labeling(self) -> None:
        self._labeled_series = []
        self._label_index = 0
        self._show_next_series()

    def _show_next_series(self) -> None:
        if self._label_index >= len(self._series_groups):
            self._finish_labeling()
            return

        self._clear_content()
        group = self._series_groups[self._label_index]

        from simpleBIDS.gui.series_panel import SeriesPanel
        from simpleBIDS.gui.label_form import LabelForm

        container = ttk.Frame(self._content)
        container.pack(fill=tk.BOTH, expand=True)

        SeriesPanel(container, series_group=group).pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        LabelForm(
            container,
            series_group=group,
            on_submit=self._on_label_submit,
            on_skip=self._on_label_skip,
            on_back=self._on_label_back,
            current=self._label_index + 1,
            total=len(self._series_groups),
        ).pack(fill=tk.BOTH, expand=True, side=tk.RIGHT)

    def _on_label_submit(self, labeled: LabeledSeries) -> None:
        self._labeled_series.append(labeled)
        self._save_cache()
        self._label_index += 1
        self._show_next_series()

    def _on_label_skip(self) -> None:
        self._label_index += 1
        self._show_next_series()

    def _on_label_back(self) -> None:
        if self._label_index > 0:
            self._label_index -= 1
            if self._labeled_series:
                self._labeled_series.pop()
        self._show_next_series()

    def _finish_labeling(self) -> None:
        scaffold_bids(self._output_dir)
        config = build_config(self._labeled_series)
        config_path = self._output_dir / "code" / "dcm2bids_config.json"
        write_config(config, config_path)
        self._show_conversion(config_path)

    # ------------------------------------------------------------------
    # Step 5 — Conversion
    # ------------------------------------------------------------------

    def _show_conversion(self, config_path: Path) -> None:
        self._clear_content()
        from simpleBIDS.gui.progress_panel import ProgressPanel
        panel = ProgressPanel(self._content, title="Converting…")
        panel.pack(fill=tk.BOTH, expand=True)

        import threading
        thread = threading.Thread(
            target=self._do_convert, args=(config_path, panel), daemon=True
        )
        thread.start()

    def _do_convert(self, config_path: Path, panel) -> None:
        participants_path = self._output_dir / "participants.tsv"
        # Collect the first staging_dir per (subject, session); with the
        # hierarchical layout staging_dir.parent is the per-session directory.
        subjects: dict[tuple[str | None, str | None], Path | None] = {}
        for group in self._series_groups:
            key = (group.subject_id, group.session_id)
            subjects.setdefault(key, group.staging_dir)

        all_ok = True
        for (subject_id, session_id), staging_dir in subjects.items():
            if staging_dir is None:
                continue
            ok = convert_subject(
                subject_id=subject_id or "unknown",
                session_id=session_id or "01",
                staging_dir=staging_dir.parent,
                bids_root=self._output_dir,
                config_path=config_path,
                participants_path=participants_path,
                progress_callback=lambda msg: self.after(0, lambda m=msg: panel.log(m)),
            )
            all_ok = all_ok and ok

        if all_ok:
            cleanup_staging(self._output_dir)
            self.after(0, lambda: panel.log("Conversion complete. Staging directory removed."))
        else:
            self.after(0, lambda: panel.log("Some conversions failed — check logs."))

    # ------------------------------------------------------------------
    # Cache / session persistence
    # ------------------------------------------------------------------

    def _cache_dir(self) -> Path | None:
        if self._output_dir is None:
            return None
        d = self._output_dir / _CACHE_DIRNAME
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_manifest(self) -> None:
        """Persist the scanned series groups in the CLI-compatible manifest format."""
        cache_dir = self._cache_dir()
        if cache_dir is None:
            return
        manifest = []
        for i, group in enumerate(self._series_groups):
            manifest.append({
                "index": i,
                "series_description": group.series_description,
                "series_number": group.series_number,
                "modality": group.modality,
                "file_count": group.file_count,
                "representative_file": str(group.representative_file),
                "all_files": [str(f) for f in group.all_files],
                "subject_id": group.subject_id,
                "session_id": group.session_id,
                "suggested_datatype": group.suggested_datatype,
                "suggested_suffix": group.suggested_suffix,
                "is_localizer": group.is_localizer,
                "staging_dir": str(group.staging_dir) if group.staging_dir else None,
                "slug": group.slug,
                "slice_png": None,
            })
        try:
            (cache_dir / _MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Could not save manifest: %s", exc)

    def _save_cache(self) -> None:
        """Persist labeling decisions so the session can be resumed."""
        cache_dir = self._cache_dir()
        if cache_dir is None:
            return

        # Serialize each labeled decision by its position in _series_groups
        decisions = []
        for ls in self._labeled_series:
            try:
                series_index = self._series_groups.index(ls.series_group)
            except ValueError:
                series_index = -1
            decisions.append({
                "series_index": series_index,
                "datatype": ls.datatype,
                "suffix": ls.suffix,
                "entities": ls.entities,
                "custom_criteria": ls.custom_criteria,
                "exclude": ls.exclude,
            })

        cache = {
            "input_dir": str(self._input_dir),
            "output_dir": str(self._output_dir),
            "label_index": self._label_index,
            "labeled_decisions": decisions,
        }
        try:
            (cache_dir / _SESSION_NAME).write_text(
                json.dumps(cache, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Could not save session cache: %s", exc)

    def _load_cache(self, session_path: Path) -> None:
        """Restore a previous session without re-scanning.

        Loads the scan results from the CLI-compatible manifest and
        reconstructs the labeled decisions from the saved decision list.
        Falls back to a full re-scan if the manifest is missing.
        """
        try:
            cache = json.loads(session_path.read_text(encoding="utf-8"))
            self._input_dir = Path(cache["input_dir"])
            self._output_dir = Path(cache["output_dir"])

            manifest_path = self._output_dir / _CACHE_DIRNAME / _MANIFEST_NAME
            if manifest_path.exists():
                from simpleBIDS.cli.label import _group_from_entry
                manifest: list[dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._series_groups = [_group_from_entry(e) for e in manifest]

                # Restore labeled decisions from saved indices
                self._labeled_series = []
                for decision in cache.get("labeled_decisions", []):
                    idx = decision.get("series_index", -1)
                    if 0 <= idx < len(self._series_groups):
                        self._labeled_series.append(LabeledSeries(
                            series_group=self._series_groups[idx],
                            datatype=decision.get("datatype", "anat"),
                            suffix=decision.get("suffix", "T1w"),
                            entities=decision.get("entities", {}),
                            custom_criteria=decision.get("custom_criteria", {}),
                            exclude=decision.get("exclude", False),
                        ))

                self._label_index = cache.get("label_index", 0)
                self.after(0, self._show_study_config)
            else:
                # Manifest missing — fall back to full re-scan
                logger.warning("Session manifest not found; re-scanning from scratch")
                self._input_var.set(str(self._input_dir))
                self._output_var.set(str(self._output_dir))
                self._start_scan()

        except Exception as exc:
            messagebox.showerror("Cache error", f"Could not resume session: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_content(self) -> None:
        for widget in self._content.winfo_children():
            widget.destroy()


def run_label_gui(
    groups: list,
    manifest: list[dict],
    bids_root: Path,
) -> list[LabeledSeries] | None:
    """Launch a standalone series-labeling window and return the results.

    This is the entry point called by the ``bids-label`` CLI command.  It
    creates a minimal tkinter window that loops through *groups*, showing a
    :class:`~simpleBIDS.gui.series_panel.SeriesPanel` and
    :class:`~simpleBIDS.gui.label_form.LabelForm` for each series.

    Args:
        groups: :class:`~simpleBIDS.patterns.series_grouper.SeriesGroup` list
            produced by :func:`~simpleBIDS.cli.label._group_from_entry`.
        manifest: Raw manifest entry dicts from ``series_manifest.json``
            (used for future slice-PNG lookup; currently unused directly).
        bids_root: BIDS project root (reserved for session-cache writes).

    Returns:
        A list of :class:`~simpleBIDS.bids.config_builder.LabeledSeries` on
        success, or ``None`` if the user closed the window before finishing.
    """
    result: list[LabeledSeries] = []
    state = {"index": 0, "labeled": [], "cancelled": False}

    root = tk.Tk()
    root.title("simpleBIDS — Label Series")
    root.resizable(True, True)
    root.minsize(800, 600)

    bar = ttk.Frame(root, relief=tk.RIDGE)
    bar.pack(fill=tk.X, side=tk.TOP)
    ttk.Label(bar, text="simpleBIDS — Label Series", font=("TkDefaultFont", 12, "bold")).pack(
        side=tk.LEFT, padx=8, pady=4
    )

    content = ttk.Frame(root)
    content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def _clear() -> None:
        for widget in content.winfo_children():
            widget.destroy()

    def _show_next() -> None:
        i = state["index"]
        if i >= len(groups):
            _finish()
            return
        _clear()
        group = groups[i]
        container = ttk.Frame(content)
        container.pack(fill=tk.BOTH, expand=True)

        from simpleBIDS.gui.series_panel import SeriesPanel
        from simpleBIDS.gui.label_form import LabelForm

        SeriesPanel(container, series_group=group).pack(
            fill=tk.BOTH, expand=True, side=tk.LEFT
        )
        LabelForm(
            container,
            series_group=group,
            on_submit=_on_submit,
            on_skip=_on_skip,
            on_back=_on_back,
            current=i + 1,
            total=len(groups),
        ).pack(fill=tk.BOTH, expand=True, side=tk.RIGHT)

    def _on_submit(labeled: LabeledSeries) -> None:
        state["labeled"].append(labeled)
        state["index"] += 1
        _show_next()

    def _on_skip() -> None:
        state["index"] += 1
        _show_next()

    def _on_back() -> None:
        if state["index"] > 0:
            state["index"] -= 1
            if state["labeled"]:
                state["labeled"].pop()
        _show_next()

    def _finish() -> None:
        nonlocal result
        result = list(state["labeled"])
        root.destroy()

    def _on_close() -> None:
        state["cancelled"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    _show_next()
    root.mainloop()

    return None if state["cancelled"] else result


def main() -> None:
    """CLI entry point (registered in pyproject.toml)."""
    configure_logging()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
