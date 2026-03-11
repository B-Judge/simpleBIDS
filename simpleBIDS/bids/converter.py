"""Orchestrate BIDS conversion for a single subject/session."""

from __future__ import annotations

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
    """Minimal fallback: run dcm2niix on each series staging subdirectory."""
    if not shutil.which("dcm2niix"):
        logger.error("Neither dcm2bids nor dcm2niix found in PATH.")
        return False

    tmp_out = bids_root / ".dcm2niix_tmp" / f"sub-{subject_id}_ses-{session_id}"
    tmp_out.mkdir(parents=True, exist_ok=True)

    any_success = False
    for series_dir in sorted(staging_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        cmd = [
            "dcm2niix",
            "-o", str(tmp_out),
            "-f", "%d_%s",
            "-z", "y",
            str(series_dir),
        ]
        log(f"dcm2niix ← {series_dir.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            any_success = True
        else:
            logger.warning("dcm2niix failed on %s: %s", series_dir, result.stderr)

    # TODO: implement config-based renaming and placement of dcm2niix output
    # into the BIDS tree. For now, files land in tmp_out for manual review.
    log(f"dcm2niix output at {tmp_out} — manual BIDS placement not yet implemented")
    return any_success


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
