"""Orchestrate BIDS conversion for a single subject/session."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from simpleBIDS.bids.participants import ParticipantRecord, ParticipantsTable

logger = logging.getLogger(__name__)


def convert_subject(
    subject_id: str,
    session_id: str,
    staging_dir: Path,
    bids_root: Path,
    config_path: Path,
    participants_path: Path,
    *,
    progress_callback: Callable[[str], None] | None = None,
    participant_record: ParticipantRecord | None = None,
) -> bool:
    """Run conversion for one subject/session and update participants.tsv.

    Attempts to use ``dcm2bids`` (subprocess) if available. Falls back to
    running ``dcm2niix`` directly on the staging directory and placing the
    resulting files into the BIDS tree.

    Args:
        subject_id: BIDS subject label (without ``sub-`` prefix).
        session_id: BIDS session label (without ``ses-`` prefix).
        staging_dir: Per-subject/session staging directory containing
            per-series symlinked subdirectories.
        bids_root: Root of the BIDS output project.
        config_path: Path to the ``dcm2bids_config.json``.
        participants_path: Path to ``participants.tsv`` to update.
        progress_callback: Optional callable receiving progress strings.
        participant_record: Optional record to write into participants.tsv.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    _log = progress_callback or (lambda msg: logger.info(msg))

    _log(f"Converting sub-{subject_id} ses-{session_id}…")

    success = False
    if shutil.which("dcm2bids"):
        success = _run_dcm2bids(
            subject_id, session_id, staging_dir, bids_root, config_path, _log
        )
    else:
        logger.warning("dcm2bids not found; falling back to dcm2niix")
        success = _run_dcm2niix_fallback(
            subject_id, session_id, staging_dir, bids_root, config_path, _log
        )

    if success:
        _update_participants(participants_path, subject_id, participant_record)
        _log(f"sub-{subject_id} ses-{session_id} complete.")

    return success


def _run_dcm2bids(
    subject_id: str,
    session_id: str,
    staging_dir: Path,
    bids_root: Path,
    config_path: Path,
    log: Callable[[str], None],
) -> bool:
    cmd = [
        "dcm2bids",
        "--dicom_dir", str(staging_dir),
        "--participant", subject_id,
        "--session", session_id,
        "--config", str(config_path),
        "--output_dir", str(bids_root),
    ]
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        log(result.stdout)
    if result.returncode != 0:
        logger.error("dcm2bids failed:\n%s", result.stderr)
        return False
    return True


def _run_dcm2niix_fallback(
    subject_id: str,
    session_id: str,
    staging_dir: Path,
    bids_root: Path,
    config_path: Path,
    log: Callable[[str], None],
) -> bool:
    """Fallback: run dcm2niix per series staging subdirectory, then place files into BIDS tree.

    For each series directory under *staging_dir*, dcm2niix is run into a
    temporary output directory.  The resulting NIfTI files are then matched
    against the ``descriptions`` in *config_path* by ``SeriesDescription``
    substring and moved into the correct BIDS subject/session/datatype path.
    The temporary directory is removed on completion.
    """
    if not shutil.which("dcm2niix"):
        logger.error("Neither dcm2bids nor dcm2niix found in PATH.")
        return False

    config = _load_config(config_path)
    descriptions = config.get("descriptions", [])

    tmp_out = bids_root / ".dcm2niix_tmp" / f"sub-{subject_id}_ses-{session_id}"
    tmp_out.mkdir(parents=True, exist_ok=True)

    any_success = False
    for series_dir in sorted(staging_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        series_tmp = tmp_out / series_dir.name
        series_tmp.mkdir(parents=True, exist_ok=True)
        cmd = [
            "dcm2niix",
            "-o", str(series_tmp),
            "-f", "%d_%s",
            "-z", "y",
            str(series_dir),
        ]
        log(f"dcm2niix ← {series_dir.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            any_success = True
            _place_nifti_files(
                series_tmp, subject_id, session_id, bids_root, descriptions, log
            )
        else:
            logger.warning("dcm2niix failed on %s: %s", series_dir, result.stderr)

    try:
        shutil.rmtree(tmp_out)
    except Exception as exc:
        logger.warning("Could not remove temporary directory %s: %s", tmp_out, exc)

    return any_success


def _load_config(config_path: Path) -> dict:
    """Load dcm2bids config JSON; return an empty dict on any error."""
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load config at %s: %s", config_path, exc)
        return {}


def _place_nifti_files(
    src_dir: Path,
    subject_id: str,
    session_id: str,
    bids_root: Path,
    descriptions: list[dict],
    log: Callable[[str], None],
) -> None:
    """Move dcm2niix NIfTI output into the BIDS tree using config descriptions.

    Each ``*.nii.gz`` (or ``*.nii``) file in *src_dir* is matched to a config
    description by ``SeriesDescription`` substring.  Both the NIfTI and its
    JSON sidecar (if present) are moved to the appropriate BIDS destination:
    ``<bids_root>/sub-<sub>/ses-<ses>/<datatype>/<bids_filename>.<ext>``.
    """
    nii_files = sorted(
        p for p in src_dir.iterdir()
        if p.suffix in {".nii", ".gz"} and ".nii" in p.name
    )
    if not nii_files:
        return

    for nii_path in nii_files:
        stem = nii_path.name.replace(".nii.gz", "").replace(".nii", "")
        match = _match_description(stem, descriptions)

        if match is None:
            logger.warning(
                "No matching config description for '%s'; skipping BIDS placement.",
                nii_path.name,
            )
            continue

        datatype = match.get("datatype", "anat")
        suffix = match.get("suffix", "T1w")
        entities: dict[str, str] = match.get("custom_entities", {})
        bids_name = _build_bids_filename(subject_id, session_id, entities, suffix)

        dest_dir = bids_root / f"sub-{subject_id}" / f"ses-{session_id}" / datatype
        dest_dir.mkdir(parents=True, exist_ok=True)

        for src_ext in (".nii.gz", ".nii", ".json"):
            src = src_dir / (stem + src_ext)
            if src.exists():
                dest = dest_dir / (bids_name + src_ext)
                shutil.move(str(src), str(dest))
                log(f"  → {dest.relative_to(bids_root)}")


def _match_description(stem: str, descriptions: list[dict]) -> dict | None:
    """Return the first config description whose ``SeriesDescription`` is a
    case-insensitive substring of *stem*, or ``None`` if no match is found.

    If only one description is present, it is returned unconditionally as a
    last-resort fallback.
    """
    stem_lower = stem.lower()
    for desc in descriptions:
        series_desc = desc.get("criteria", {}).get("SeriesDescription", "")
        if series_desc and series_desc.lower() in stem_lower:
            return desc
    if len(descriptions) == 1:
        return descriptions[0]
    return None


def _build_bids_filename(
    subject_id: str,
    session_id: str,
    entities: dict[str, str],
    suffix: str,
) -> str:
    """Assemble a BIDS-compliant filename stem (without extension).

    Entity order follows the BIDS recommended ordering: task, acq, ce, dir,
    rec, run, echo, part.
    """
    parts = [f"sub-{subject_id}", f"ses-{session_id}"]
    for key in ("task", "acq", "ce", "dir", "rec", "run", "echo", "part"):
        if key in entities:
            parts.append(f"{key}-{entities[key]}")
    parts.append(suffix)
    return "_".join(parts)


def _update_participants(
    participants_path: Path,
    subject_id: str,
    record: ParticipantRecord | None,
) -> None:
    table = ParticipantsTable.load(participants_path)
    bids_id = f"sub-{subject_id}"
    if record is None:
        record = ParticipantRecord(participant_id=bids_id)
    else:
        record.participant_id = bids_id
    table.add(record)
    table.save(participants_path)
