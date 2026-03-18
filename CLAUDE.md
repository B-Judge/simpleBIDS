# simpleBIDS

## Project Overview

simpleBIDS is a Python tool for automatically organizing neuroimaging data (DICOM and NIfTI) into [BIDS format](https://bids-specification.readthedocs.io/). It minimizes user burden by automatically inferring subject/session identifiers, detecting series patterns, and generating conversion configs — only prompting the user to verify image type labels via a lightweight tkinter GUI.

The BIDS specification is included as a git submodule at `bids-specification/`. All valid BIDS data types, suffixes, entities, and rules must be derived from the machine-readable schema located at `bids-specification/src/schema/` rather than hardcoded. This ensures the tool stays current with the spec and is the single source of truth for any BIDS naming decisions.

---

## Goals

1. Scan raw neuroimaging data directories (DICOM and/or NIfTI)
2. Infer subject and session identifiers from headers and file paths
3. Detect patterns in series descriptions and image characteristics
4. Sort data into a **symlinked staging directory** (one subdirectory per series, containing symlinks to the originals) so `dcm2niix` can run cleanly per series
5. Present representative image slices + series descriptions to the user via GUI
6. Collect user input on modality/suffix pairings (with smart defaults sourced from the BIDS schema submodule)
7. Auto-generate a `dcm2bids_config.json` (or internal equivalent)
8. Run BIDS conversion (via dcm2bids or internal reimplementation)
9. Scaffold a valid BIDS project directory structure
10. Maintain `participants.tsv` automatically as subjects are processed

---

## Architecture

Prioritize **modularity**, **separation of concerns**, and **testability**. Each module must be independently importable and usable without the GUI.

```
simpleBIDS/
├── bids-specification/           # git submodule — BIDS schema source of truth
│   └── src/schema/               # machine-readable YAML schema files
├── simpleBIDS/
│   ├── __init__.py
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── dicom_parser.py       # DICOM header extraction and metadata
│   │   ├── nifti_parser.py       # NIfTI/JSON sidecar parsing
│   │   └── path_parser.py        # Subject/session inference from file paths
│   ├── patterns/
│   │   ├── __init__.py
│   │   ├── series_grouper.py     # Group DICOMs/NIfTIs by series description
│   │   ├── slice_sampler.py      # Extract representative image slices
│   │   └── symlink_sorter.py     # Build per-series symlinked staging directories
│   ├── inference/
│   │   ├── __init__.py
│   │   ├── subject_inference.py  # Subject ID detection from headers + paths
│   │   └── session_inference.py  # Session ID detection (default: scan date)
│   ├── bids/
│   │   ├── __init__.py
│   │   ├── scaffold.py           # Generate BIDS directory structure
│   │   ├── participants.py       # Read/write/update participants.tsv
│   │   ├── config_builder.py     # Build dcm2bids_config.json
│   │   └── converter.py          # BIDS conversion orchestration
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── app.py                # Main tkinter application entry point
│   │   ├── series_panel.py       # Display series description + image slice
│   │   ├── label_form.py         # Modality/suffix input form with suggestions
│   │   ├── study_config.py       # Study-level naming conventions panel
│   │   └── progress_panel.py     # Conversion progress display
│   ├── schema/
│   │   ├── __init__.py
│   │   └── bids_schema.py        # Load and query bids-specification/src/schema/
│   └── utils/
│       ├── __init__.py
│       ├── filesystem.py         # Path utilities, directory walking
│       └── logging.py            # Structured logging setup
├── tests/
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

---

## Module Specifications

### `parsers/dicom_parser.py`
- Use `pydicom` for header reading
- Extract: `SeriesDescription`, `Modality`, `PatientID`, `PatientName`, `StudyDate`, `SeriesDate`, `AcquisitionDate`, `StudyDescription`, `InstitutionName`, `SeriesNumber`, `ImageType`, `ProtocolName`
- Return a structured dataclass or dict per DICOM file/series
- Deduplicate at series level — do not load every slice's headers; sample one representative file per series
- Handle missing/malformed tags gracefully; log warnings, never raise on missing optional fields

### `parsers/nifti_parser.py`
- Use `nibabel` for NIfTI header reading
- Parse companion JSON sidecars (BIDS-style) when present
- Extract: dimensions, voxel size, TR, phase encoding direction, task name if present
- Fall back gracefully if no sidecar exists

### `parsers/path_parser.py`
- Implement regex-based heuristics to extract subject/session hints from directory and file names
- Common patterns: `sub-001`, `S001`, `PAT_001`, date strings (`20230415`, `2023-04-15`), session keywords (`ses-01`, `visit1`, `baseline`, `followup`)
- Return candidates ranked by confidence, not a single answer

### `inference/subject_inference.py`
- Priority order for subject ID:
  1. DICOM `PatientID` (cleaned/normalized)
  2. DICOM `PatientName` (if `PatientID` is absent or generic)
  3. Regex match from directory/file name
- Normalize to BIDS-safe strings (alphanumeric only, no spaces/special chars)
- Expose `infer_subject(dicom_metadata, filepath) -> str`

### `inference/session_inference.py`
- Priority order for session ID:
  1. `SeriesDate` or `AcquisitionDate` from DICOM headers (formatted as `YYYYMMDD`)
  2. `StudyDate` fallback
  3. Regex date match from path
  4. Session keywords from path (`baseline`, `followup`, `visit1`, etc.)
  5. Fall back to `ses-01` if nothing found
- Expose `infer_session(dicom_metadata, filepath) -> str`

### `patterns/series_grouper.py`
- Group DICOM files into series using: `SeriesDescription` + `SeriesNumber` + `Modality`
- For NIfTI input, group by filename stem patterns and sidecar fields
- Output: list of `SeriesGroup` objects, each containing:
  - Series description string
  - Representative file path(s)
  - Count of files/slices
  - Inferred modality hints (from `Modality` tag or filename patterns)
  - BIDS suffix suggestions (heuristic, not final)

### `patterns/slice_sampler.py`
- For each `SeriesGroup`, extract a single representative 2D image slice
- For DICOM: load middle slice using `pydicom`, extract pixel array
- For NIfTI: load with `nibabel`, extract middle axial slice
- Normalize pixel values for display (min-max or percentile clipping)
- Return a numpy array suitable for display in tkinter via PIL/Pillow

### `patterns/symlink_sorter.py`
- After series grouping, build a staging directory (default: `<output>/.simpleBIDS_staging/`) containing one subdirectory per `SeriesGroup`
- Each subdirectory is named unambiguously: `{subject}_{session}_{series_number}_{series_description_slug}/`
- Populate each subdirectory with **symlinks** (not copies) pointing to the original DICOM files or NIfTI file for that series
- This structure lets `dcm2niix` run independently per series directory with no cross-contamination between series
- Symlinks must be relative where possible so the staging tree is relocatable
- Expose: `build_staging(series_groups: list[SeriesGroup], staging_root: Path) -> dict[SeriesGroup, Path]`
- Staging directory is ephemeral — it can be deleted after conversion succeeds; document this clearly

### `schema/bids_schema.py`
- Load the machine-readable BIDS schema from `bids-specification/src/schema/` (YAML files) at import time or on first access
- Expose query helpers:
  - `get_datatypes() -> list[str]` — valid BIDS data type folders (anat, func, dwi, fmap, etc.)
  - `get_suffixes(datatype: str) -> list[str]` — valid suffixes for a given datatype
  - `get_entities(datatype: str, suffix: str) -> list[str]` — valid BIDS entities (sub, ses, task, run, etc.)
  - `get_required_entities(datatype: str, suffix: str) -> list[str]` — required vs optional entities
  - `validate_suffix(datatype: str, suffix: str) -> bool`
- Cache parsed schema in memory; never re-parse on repeated calls
- If the submodule is not initialized, raise a clear error pointing the user to `git submodule update --init`
- This module is the **only** place in the codebase that should hardcode the schema path; all other modules import from here

### `bids/scaffold.py`
- Create standard BIDS top-level files and directories:
  - `dataset_description.json` (prompt user for Name, BIDSVersion, Authors)
  - `participants.tsv` (initialized with headers)
  - `participants.json`
  - `README`
  - `.bidsignore`
  - `code/`, `derivatives/`, `sourcedata/` directories
- Do not overwrite existing files; merge or skip with warning

### `bids/participants.py`
- Load, update, and save `participants.tsv`
- Columns: at minimum `participant_id`; extend with `age`, `sex`, `session` if available from headers
- Deduplicate entries by `participant_id`
- Expose: `load(path)`, `add_participant(record)`, `save(path)`

### `bids/config_builder.py`
- Build `dcm2bids_config.json` from the list of user-labeled series
- Each entry maps a series description pattern to a `dataType` (BIDS folder) and `suffix`
- Support custom criteria fields (`SeriesNumber`, `ImageType`, etc.) where needed for disambiguation
- Expose: `build_config(labeled_series: list[LabeledSeries]) -> dict`
- Write config to `code/dcm2bids_config.json` by default

### `bids/converter.py`
- Orchestrate the full conversion pipeline per subject/session
- Attempt to use `dcm2bids` CLI via subprocess if installed
- If dcm2bids is unavailable or the user opts out, implement internal conversion using `dcm2niix` subprocess + BIDS file renaming/placement logic
- After each subject converts successfully, call `participants.add_participant()`
- Log conversion output; surface errors clearly

### `gui/app.py`
- Main `tk.Tk` window — minimal, functional, not decorative
- Workflow steps:
  1. Input directory selection (raw data root)
  2. Output directory selection (BIDS root)
  3. Automatic scan + grouping (progress shown)
  4. Series labeling loop (one series per screen)
  5. Study config review
  6. Conversion with live progress
- Support resuming interrupted sessions (cache grouped series + labels to disk as JSON)

### `gui/series_panel.py`
- Display: series description text, file count, inferred modality hint
- Show representative image slice using `PIL.ImageTk`
- Navigation: Previous / Skip / Next buttons
- Display current progress (e.g., "Series 3 of 12")

### `gui/label_form.py`
- Dropdown for `dataType` — values sourced from `schema.get_datatypes()`, never hardcoded
- Dropdown for `suffix` — values sourced from `schema.get_suffixes(selected_datatype)`, updates dynamically when dataType changes
- Required entity fields rendered dynamically from `schema.get_required_entities(datatype, suffix)` (e.g., task name for func, direction for fmap)
- Optional entity fields shown but not mandatory
- Pre-populate dropdowns with heuristic suggestions from series grouper
- "Apply to all matching" checkbox for bulk labeling identical series descriptions
- Custom free-text entry allowed for suffix/entities if user needs a value not in the schema (with a warning that it may not pass BIDS validation)

### `gui/study_config.py`
- Display and allow editing of:
  - Inferred subject IDs (with option to override)
  - Inferred session IDs (with option to override)
  - Study name / dataset description fields
- Show a summary table of subjects x sessions found

---

## Data Flow

```
Raw data directory
       │
       ▼
[parsers] ──► SeriesGroups + SubjectSession records
       │
       ▼
[inference] ──► subject_id, session_id per dataset
       │
       ▼
[symlink_sorter] ──► .simpleBIDS_staging/{series_dirs}/ (symlinks to originals)
       │
       ▼
[gui: study_config] ──► user verifies/overrides subject+session
       │
       ▼
[schema/bids_schema] ──► valid datatypes, suffixes, entities (from submodule)
       │
       ▼
[gui: series_panel + label_form] ──► user labels each series
       │
       ▼
[config_builder] ──► dcm2bids_config.json
       │
       ▼
[bids/scaffold] ──► BIDS directory created
       │
       ▼
[converter] ──► dcm2niix runs per staging series directory → BIDS output
       │
       ▼
[participants] ──► participants.tsv updated
       │
       ▼
[symlink_sorter] ──► staging directory cleaned up
```

---

## Development Conventions

- **Python 3.10+**
- Use `dataclasses` or `pydantic` models for structured data (prefer dataclasses to avoid heavy dependencies)
- Type hints on all public functions
- Logging via stdlib `logging` module — no bare `print()` in library code
- All file I/O uses `pathlib.Path`, never string concatenation for paths
- Tests go in `tests/` using `pytest`; mock filesystem and DICOM data, do not require real neuroimaging files for unit tests
- No hard dependency on dcm2bids or dcm2niix in core library code — these are optional runtime dependencies checked at call time
- GUI code must never be imported by non-GUI modules (no circular dependencies from parsers into tkinter)

## Key Dependencies

- `pydicom` — DICOM parsing
- `nibabel` — NIfTI parsing
- `numpy` — array operations on image data
- `Pillow` — image display in tkinter
- `pyyaml` — parsing BIDS schema YAML files from submodule
- `tkinter` — GUI (stdlib)
- `pytest` — testing

Optional runtime:
- `dcm2niix` — DICOM to NIfTI conversion (subprocess, called per staging series directory)
- `dcm2bids` — BIDS conversion (subprocess, may be replaced internally)

Git submodule (bundled, not a pip dependency):
- `bids-specification` — BIDS schema at `bids-specification/src/schema/`; initialize with `git submodule update --init`

---

## Command-Line Interface

The tool exposes five CLI entry points, registered in `pyproject.toml` under `[project.scripts]`. Each command maps to a module in `simpleBIDS/cli/`.

```
simpleBIDS/
├── simpleBIDS/
│   └── cli/
│       ├── __init__.py
│       ├── init.py           # bids-init
│       ├── sort.py           # bids-sort
│       ├── label.py          # bids-label
│       ├── convert.py        # bids-convert
│       └── update_participants.py  # bids-update-participants
```

### `bids-init <bids_dir>`

Scaffolds a new BIDS project directory at the given path.

- Calls `bids.scaffold` to create the standard BIDS top-level structure
- Creates `sourcedata/` as the designated drop location for raw neuroimaging data
- Prints a short message instructing the user to place unorganized data in `sourcedata/` before running `bids-sort`
- Accepts an optional `--name` flag to set the dataset name in `dataset_description.json` non-interactively; otherwise prompts interactively
- Exits with a clear error if the directory already exists and looks like a BIDS project

### `bids-sort <bids_dir>`

Scans `<bids_dir>/sourcedata/`, groups series, and builds the symlinked staging structure.

- Walks `sourcedata/` and runs all parsers (DICOM and/or NIfTI) to produce `SeriesGroup` objects
- Runs subject/session inference on each group
- Calls `symlink_sorter.build_staging()` to populate `<bids_dir>/.simpleBIDS_staging/`
- Saves representative image slices (PNG) and per-series metadata (JSON) to `<bids_dir>/.simpleBIDS_cache/` for use by `bids-label`
- Writes a machine-readable `series_manifest.json` to `.simpleBIDS_cache/` summarising all detected series, inferred subject/session IDs, file counts, and paths to cached slices
- Prints a summary table of series found on completion
- Is idempotent: re-running clears and rebuilds the staging and cache directories

### `bids-label <bids_dir>`

Opens the tkinter GUI loaded from the cached series data produced by `bids-sort`.

- Reads `.simpleBIDS_cache/series_manifest.json`; errors clearly if `bids-sort` has not been run
- Launches `gui.app` in label-only mode (no re-scanning): shows each series' cached image slice and metadata
- User assigns `dataType` + `suffix` (and required entities) to each series via `gui.label_form`
- User can review/override inferred subject and session IDs via `gui.study_config`
- On completion, writes `<bids_dir>/code/dcm2bids_config.json` via `bids.config_builder`
- Supports `--headless` flag that skips the GUI and applies heuristic auto-labeling only (for automated pipelines); outputs config and exits

### `bids-convert <bids_dir>`

Applies `dcm2bids_config.json` and converts staged data to BIDS format.

- Reads `<bids_dir>/code/dcm2bids_config.json`; errors clearly if `bids-label` has not been run
- For each subject/session found in the staging directory, invokes `dcm2bids` (preferred) or falls back to `dcm2niix` + internal renaming via `bids.converter`
- Runs conversion per staging series directory for clean isolation
- Writes converted files into the BIDS subject/session tree under `<bids_dir>`
- On success, cleans up the staging directory (`.simpleBIDS_staging/`) and optionally the cache (`.simpleBIDS_cache/`) unless `--keep-staging` is passed
- Prints per-subject conversion status; exits non-zero if any subject fails

### `bids-update-participants <bids_dir>`

Scans the BIDS project and synchronizes `participants.tsv` with what is actually present on disk.

- Walks the BIDS subject/session tree and discovers all `sub-*` directories
- For each subject/session, records: `participant_id`, `session_id`, detected image modalities (by datatype folder), and relative file paths to NIfTI files
- Merges discovered records into `participants.tsv` via `bids.participants` without overwriting manually added columns (e.g., `age`, `sex`)
- Adds new participants, updates existing rows for new sessions/modalities, and optionally flags (but does not delete) participants present in TSV but missing from disk
- Prints a diff-style summary of additions and updates made

---

## Out of Scope (for now)

- MEG, EEG, iEEG support (scaffold for it, but do not implement parsers)
- Cloud storage backends
- BIDS validation (recommend users run the BIDS Validator separately)
- Multi-site dataset merging
