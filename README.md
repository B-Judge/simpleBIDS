# simpleBIDS

A Python tool for automatically organizing neuroimaging data (DICOM and NIfTI)
into [BIDS format](https://bids-specification.readthedocs.io/).

simpleBIDS minimizes manual effort by inferring subject/session identifiers from
DICOM headers and file paths, detecting series patterns, and generating
conversion configs. The user is only asked to verify image-type labels — either
interactively through a lightweight tkinter GUI or fully automatically in
`--headless` mode.

---

## Requirements

- Python 3.10+
- `pydicom`, `nibabel`, `numpy`, `Pillow`, `PyYAML`
- `dcm2bids` (preferred) or `dcm2niix` at conversion time
- `tkinter` for the GUI (standard library on most platforms; install `python3-tk`
  if missing on Linux)

Initialize the BIDS specification submodule after cloning:

```bash
git submodule update --init
```

Install the package and its dependencies:

```bash
pip install -e .
```

---

## Workflow

The tool exposes five CLI commands that are run in order.

### 1 — `bids-init`

Create a new BIDS project directory.

```bash
bids-init /data/my_study --name "Resting State Cohort 2024"
```

Creates the standard BIDS scaffold:
`dataset_description.json`, `participants.tsv`, `participants.json`, `README`,
`.bidsignore`, and the `code/`, `derivatives/`, `sourcedata/` folders.

After running this command, place your raw DICOM or NIfTI data inside
`sourcedata/` before continuing.

---

### 2 — `bids-sort`

Scan `sourcedata/`, group series, and build the symlinked staging tree.

```bash
bids-sort /data/my_study
```

- Walks `sourcedata/` and reads DICOM and NIfTI headers
- Groups files into per-series collections
- Infers subject and session IDs from DICOM tags and file paths
- Creates symlinked staging directories under `.simpleBIDS_staging/` so that
  `dcm2niix` can run on one series at a time with no cross-contamination
- Caches a representative PNG slice and metadata JSON per series
- Writes `.simpleBIDS_cache/series_manifest.json` for use by `bids-label`

This command is **idempotent** — re-running clears and rebuilds both the staging
and cache directories.

---

### 3 — `bids-label`

Assign BIDS datatype and suffix labels to each detected series.

```bash
# Interactive GUI
bids-label /data/my_study

# Headless — apply heuristic auto-labeling, no GUI required
bids-label /data/my_study --headless
```

**GUI mode** shows:
- A representative image slice for each series
- The inferred series description, modality, subject, and session
- Dropdown menus for BIDS `datatype` (`anat`, `func`, `dwi`, `fmap`, …) and
  `suffix` (`T1w`, `bold`, `dwi`, …) populated directly from the bundled BIDS
  specification schema
- Required entity fields rendered dynamically (e.g. `task` for `func/bold`)

**Headless mode** applies keyword-based heuristics to the series descriptions
without user interaction. Review the generated config before converting.

On completion, writes `code/dcm2bids_config.json`.

---

### 4 — `bids-convert`

Apply the config and convert staged data to BIDS format.

```bash
bids-convert /data/my_study

# Keep the staging tree for debugging
bids-convert /data/my_study --keep-staging
```

- Preferred: calls `dcm2bids` (wraps `dcm2niix` with automatic BIDS renaming)
- Fallback: calls `dcm2niix` directly and places output into the BIDS tree
  using the series descriptions in `dcm2bids_config.json`
- Updates `participants.tsv` after each successful subject
- Removes `.simpleBIDS_staging/` on success (unless `--keep-staging` is set)

---

### 5 — `bids-update-participants`

Synchronize `participants.tsv` with converted data on disk.

```bash
bids-update-participants /data/my_study
```

- Walks all `sub-*` directories in the BIDS root
- Adds rows for newly found subjects
- Updates existing rows with current modality information (`anat`, `func`, …)
- Preserves manually added columns (e.g. `age`, `sex`) — never overwrites them
- Warns about participants present in the TSV but missing from disk (does not
  delete them)

---

## Architecture

```
simpleBIDS/
├── bids-specification/       # git submodule — BIDS schema source of truth
├── simpleBIDS/
│   ├── parsers/              # DICOM, NIfTI, and path-based header extraction
│   ├── inference/            # Subject and session ID inference
│   ├── patterns/             # Series grouping, slice sampling, symlink staging
│   ├── schema/               # BIDS schema loader (reads submodule YAML)
│   ├── bids/                 # Scaffold, participants.tsv, config builder, converter
│   ├── gui/                  # tkinter GUI (app, series panel, label form, …)
│   ├── cli/                  # Five CLI entry points
│   └── utils/                # Filesystem helpers, logging, progress bar
└── tests/                    # pytest test suite
```

All valid BIDS datatypes, suffixes, and entities are derived at runtime from
the machine-readable schema in `bids-specification/src/schema/`. Nothing is
hardcoded; the tool stays current with the spec automatically.

Each module is independently importable and usable without the GUI.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite mocks filesystem and DICOM data; no real neuroimaging files are
required to run the tests.
