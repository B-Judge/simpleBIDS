"""Group DICOM or NIfTI files into per-series collections.

BIDS label heuristics
---------------------
After grouping, each :class:`SeriesGroup` is annotated with ``suggested_datatype``
and ``suggested_suffix``.  These are *heuristic* guesses derived from:

* ``SeriesDescription`` keywords (highest weight)
* ``Modality`` DICOM tag
* ``ImageType`` DICOM tag (e.g. DIFFUSION, LOCALIZER)
* File count / ``NumberOfTemporalPositions`` for functional series

The suggestions pre-populate the GUI dropdowns.  Users can override any value
before conversion.  Non-MR modalities (CT, PT) get a direct mapping; MR relies
on the keyword rules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class SeriesGroup:
    """All files belonging to a single imaging series."""

    series_description: str | None
    series_number: int | None
    modality: str | None
    all_files: list[Path]
    representative_file: Path
    file_count: int
    # Populated by inference modules after grouping
    subject_id: str | None = None
    session_id: str | None = None
    # Heuristic BIDS label suggestions (overridden by user in GUI)
    suggested_datatype: str | None = None
    suggested_suffix: str | None = None
    # True when the series looks like a localizer / scout scan
    is_localizer: bool = False
    # Staging symlink directory (set by symlink_sorter)
    staging_dir: Path | None = None
    # Full DicomMetadata / NiftiMetadata stored for downstream use
    extra: dict = field(default_factory=dict)

    @property
    def slug(self) -> str:
        """Short filesystem-safe identifier used in staging directory names."""
        parts: list[str] = []
        if self.series_number is not None:
            parts.append(f"{self.series_number:03d}")
        if self.series_description:
            safe = "".join(c if c.isalnum() else "_" for c in self.series_description)
            parts.append(safe[:48])
        return "_".join(parts) or "unknown"


# ---------------------------------------------------------------------------
# BIDS label heuristics
# ---------------------------------------------------------------------------

# Rules are checked in order; the first match wins.
# Format: (compiled_pattern, datatype, suffix)
# Use None suffix to mark "needs more info" (e.g. fmap magnitude vs phase).
_BIDS_RULES: list[tuple[re.Pattern, str, str | None]] = [
    # --- Functional --------------------------------------------------------
    # Single-band reference must come before generic BOLD
    (re.compile(r"(?i)\bsbref\b|single.?band.?ref"), "func", "sbref"),
    (re.compile(r"(?i)\bbold\b|fmri\b|rsfmri|resting.?state|rs.?fmri"
                r"|ep.?bold|epi.?bold|fcmri|task.?bold"), "func", "bold"),

    # --- Diffusion ---------------------------------------------------------
    (re.compile(r"(?i)\bdwi\b|dti\b|diffusion|d\.?tensor"
                r"|tracew|adc\b|fa\b(?=.*dwi|.*dti)|b\d{3,4}(?!\s*mm)"), "dwi", "dwi"),

    # --- Perfusion ---------------------------------------------------------
    (re.compile(r"(?i)\bm0.?scan\b|\bm0\b(?!.*bold)"), "perf", "m0scan"),
    (re.compile(r"(?i)\basl\b|arterial.?spin|pcasl|casl\b|pasl\b|vsasl"), "perf", "asl"),

    # --- Field maps (definitive keywords only) -----------------------------
    (re.compile(r"(?i)\bphasediff\b|phase.?diff"), "fmap", "phasediff"),
    (re.compile(r"(?i)\bfield.?map|b0.?map|b0map|fieldmap"), "fmap", "fieldmap"),
    # Spin-echo EPI field maps (blip-up/blip-down)
    (re.compile(r"(?i)\bse.?epi\b|spin.?echo.?epi|blip.?up|blip.?down"
                r"|ap_pa\b|pa_ap\b"), "fmap", "epi"),

    # --- Anatomical (MR) — checked before generic magnitude/phase fmap ----
    # MP2RAGE / UNIT1
    (re.compile(r"(?i)\bunit1\b|\bunit.?1\b"), "anat", "UNIT1"),
    (re.compile(r"(?i)\bmp2rage\b"), "anat", "MP2RAGE"),
    # T1 — MPRAGE, SPGR, TFL, IR-FSPGR, VFA, 3D T1, BRAVO
    (re.compile(r"(?i)\bmprage\b|t1.?w\b|t1.?spgr|3d.?t1\b|t1.?tfl"
                r"|ir.?fspgr\b|t1.?bravo|t1.?vibe\b"), "anat", "T1w"),
    # FLAIR (before T2 rules to avoid T2-FLAIR matching T2w)
    (re.compile(r"(?i)\bflair\b|t2.?flair|fluid.?attenu"), "anat", "FLAIR"),
    # T2* / SWI / GRE — before magnitude/phase fmap so "SWI_magnitude" → T2starw
    (re.compile(r"(?i)\bt2.?star\b|t2\*|swi\b|suscept|medic\b"
                r"|gre.?echo|multi.?echo(?!.*t2\b)"), "anat", "T2starw"),
    # PDw — before T2w so "PDw_TSE" matches PDw, not TSE
    (re.compile(r"(?i)\bpd.?w\b|proton.?dens"), "anat", "PDw"),
    # T2 — TSE, FSE, HASTE, SPACE, CUBE, VISTA
    (re.compile(r"(?i)\bt2.?w\b|\btse\b|\bfse\b|\bhaste\b|\bspace\b"
                r"|\bcube\b|\bvista\b"), "anat", "T2w"),
    # Angiography / MRA / TOF
    (re.compile(r"(?i)\bangio\b|\bmra\b|\btof\b|time.?of.?flight"
                r"|3d.?tof|2d.?tof"), "anat", "angio"),
    # Inversion recovery / T1-IR (generic catch-all after MP2RAGE)
    (re.compile(r"(?i)\binv.?rec|mpir\b"), "anat", "T1w"),
    # Generic T1/T2 last resort
    (re.compile(r"(?i)\bt1\b"), "anat", "T1w"),
    (re.compile(r"(?i)\bt2\b"), "anat", "T2w"),

    # --- Field maps (generic magnitude/phase — after anat-specific terms) --
    # These only fire when no named anatomical sequence was matched above.
    (re.compile(r"(?i)\bmagnitude\d?\b(?!.*angio)(?!.*mra)"), "fmap", "magnitude"),
    (re.compile(r"(?i)\bphase\d?\b(?!.*diff)(?!.*pcasl)"), "fmap", "phase"),
]

# Non-MR modalities map directly to BIDS datatype+suffix
_MODALITY_MAP: dict[str, tuple[str, str]] = {
    "CT":  ("anat", "CT"),
    "PT":  ("pet",  "pet"),
    "MG":  ("anat", "mammography"),
    "US":  ("anat", "us"),
    "DX":  ("anat", "dx"),
    "CR":  ("anat", "cr"),
    "NM":  ("pet",  "pet"),
}


def suggest_bids_labels(
    series_description: str | None,
    modality: str | None,
    image_type: list[str],
    file_count: int,
    number_of_temporal_positions: int | None = None,
) -> tuple[str | None, str | None]:
    """Return a (datatype, suffix) heuristic guess for this series.

    Args:
        series_description: DICOM SeriesDescription tag value.
        modality:            DICOM Modality tag value (e.g. ``"MR"``, ``"CT"``).
        image_type:          DICOM ImageType sequence (e.g. ``["ORIGINAL", "PRIMARY", "M"]``).
        file_count:          Number of files/slices in the series.
        number_of_temporal_positions: From the DICOM header if present.

    Returns:
        ``(datatype, suffix)`` strings or ``(None, None)`` if no guess can be made.
    """
    mod = (modality or "").upper()

    # Non-MR modalities — use direct map
    if mod in _MODALITY_MAP:
        return _MODALITY_MAP[mod]

    # For MR (and unknown modality), apply series description rules
    desc = series_description or ""
    # Normalise underscores and hyphens to spaces so that \b word boundaries
    # fire correctly on descriptions like "T1w_MPRAGE" or "BOLD-SBRef".
    desc_norm = re.sub(r"[_\-/\\]", " ", desc)

    # ImageType-based overrides (checked before description rules)
    image_type_upper = [t.upper() for t in image_type]
    if "DIFFUSION" in image_type_upper:
        return "dwi", "dwi"

    for pattern, datatype, suffix in _BIDS_RULES:
        if pattern.search(desc_norm):
            # If suffix is undetermined, try to refine from ImageType
            if suffix is None:
                suffix = _refine_fmap_suffix(image_type_upper)
            return datatype, suffix

    # Temporal heuristic: many volumes → likely functional BOLD
    n_vols = number_of_temporal_positions or file_count
    if n_vols >= 30 and mod in {"MR", ""}:
        return "func", "bold"

    return None, None


def _refine_fmap_suffix(image_type_upper: list[str]) -> str:
    """Guess fmap suffix from ImageType when description is ambiguous."""
    last = image_type_upper[-1] if image_type_upper else ""
    if last == "P":
        return "phase"
    if last == "M":
        return "magnitude"
    return "fieldmap"


# ---------------------------------------------------------------------------
# DICOM grouping
# ---------------------------------------------------------------------------

def group_dicom_series(
    dicom_root: Path,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    n_workers: int = 4,
) -> list[SeriesGroup]:
    """Walk *dicom_root* and return one :class:`SeriesGroup` per series.

    Uses :func:`~simpleBIDS.parsers.dicom_parser.scan_dicom_directory` for
    fast two-pass scanning.  Each group is annotated with heuristic BIDS
    label suggestions.

    Args:
        dicom_root: Directory containing raw DICOM data.
        progress_callback: Forwarded to the scanner; called ``(done, total)``.
        n_workers: Thread-pool size for parallel first-pass reads.

    Returns:
        List of :class:`SeriesGroup`, sorted by series number then description.
    """
    from simpleBIDS.parsers.dicom_parser import scan_dicom_directory

    dicom_series = scan_dicom_directory(
        dicom_root,
        progress_callback=progress_callback,
        n_workers=n_workers,
    )

    groups: list[SeriesGroup] = []
    for ds in dicom_series:
        meta = ds.metadata
        datatype, suffix = suggest_bids_labels(
            meta.series_description,
            meta.modality,
            meta.image_type,
            meta.file_count,
            meta.number_of_temporal_positions,
        )
        group = SeriesGroup(
            series_description=meta.series_description,
            series_number=meta.series_number,
            modality=meta.modality,
            all_files=ds.all_files,
            representative_file=ds.all_files[len(ds.all_files) // 2],
            file_count=meta.file_count,
            suggested_datatype=datatype,
            suggested_suffix=suffix,
            is_localizer=meta.is_localizer,
            extra={"dicom_metadata": meta, "series_key": ds.series_key},
        )
        groups.append(group)

    n_loc = sum(1 for g in groups if g.is_localizer)
    if n_loc:
        logger.info("%d localizer/scout series detected and flagged", n_loc)
    logger.info("Grouped %d DICOM series from %s", len(groups), dicom_root)
    return groups


# ---------------------------------------------------------------------------
# NIfTI grouping
# ---------------------------------------------------------------------------

def group_nifti_files(nifti_root: Path) -> list[SeriesGroup]:
    """Walk *nifti_root* and create one :class:`SeriesGroup` per NIfTI file.

    Heuristic BIDS labels are suggested from the filename stem and sidecar
    metadata where available.
    """
    from simpleBIDS.parsers.nifti_parser import walk_nifti_directory, parse_nifti

    niftis = walk_nifti_directory(nifti_root)
    groups: list[SeriesGroup] = []

    for path in sorted(niftis):
        try:
            meta = parse_nifti(path)
        except Exception:
            logger.warning("Skipping unreadable NIfTI: %s", path)
            continue

        # Prefer sidecar SeriesDescription, fall back to filename stem
        desc = meta.series_description or _stem_without_gz(path)
        image_type: list[str] = []
        file_count = 4 if len(meta.shape) == 4 and meta.shape[3] > 1 else 1
        n_vols = meta.shape[3] if len(meta.shape) == 4 else 1

        # Derive modality from sidecar MRAcquisitionType / Modality if present
        modality = meta.sidecar.get("Modality") or None

        datatype, suffix = suggest_bids_labels(
            desc, modality, image_type, file_count,
            number_of_temporal_positions=n_vols if n_vols > 1 else None,
        )

        groups.append(SeriesGroup(
            series_description=desc,
            series_number=None,
            modality=modality,
            all_files=[path],
            representative_file=path,
            file_count=1,
            suggested_datatype=datatype,
            suggested_suffix=suffix,
            extra={"nifti_metadata": meta},
        ))

    logger.info("Found %d NIfTI files under %s", len(groups), nifti_root)
    return groups


# ---------------------------------------------------------------------------
# Auto-detect entry point
# ---------------------------------------------------------------------------

def group_series(
    root: Path,
    *,
    mode: str = "auto",
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[SeriesGroup]:
    """Top-level entry point: group all series found under *root*.

    Args:
        root: Root directory containing raw imaging data.
        mode: ``"dicom"``, ``"nifti"``, or ``"auto"`` (detect by content).
        progress_callback: Forwarded to the DICOM scanner.

    Returns:
        Combined list of :class:`SeriesGroup` objects.
    """
    if mode == "dicom":
        return group_dicom_series(root, progress_callback=progress_callback)
    if mode == "nifti":
        return group_nifti_files(root)

    # Auto-detect: probe a few files to see what's present
    has_dcm = _probe_dicom(root)
    has_nii = _probe_nifti(root)

    groups: list[SeriesGroup] = []
    if has_dcm:
        groups += group_dicom_series(root, progress_callback=progress_callback)
    if has_nii and not has_dcm:
        groups += group_nifti_files(root)
    return groups


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _probe_dicom(root: Path, n: int = 5) -> bool:
    """Return True if any of the first *n* candidate files parse as DICOM."""
    import pydicom
    from simpleBIDS.parsers.dicom_parser import _iter_candidate_files

    for i, path in enumerate(_iter_candidate_files(root)):
        if i >= n:
            break
        try:
            pydicom.dcmread(str(path), stop_before_pixels=True,
                            specific_tags=["SOPClassUID"], force=False)
            return True
        except Exception:
            continue
    return False


def _probe_nifti(root: Path) -> bool:
    """Return True if any NIfTI files exist under *root*."""
    from simpleBIDS.parsers.nifti_parser import walk_nifti_directory
    return len(walk_nifti_directory(root)) > 0


def _stem_without_gz(path: Path) -> str:
    """Return the filename stem, stripping ``.gz`` from ``.nii.gz`` files."""
    name = path.name
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    return path.stem
