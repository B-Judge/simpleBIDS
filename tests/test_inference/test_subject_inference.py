"""Tests for subject_inference."""

from pathlib import Path
from unittest.mock import MagicMock

from simpleBIDS.inference.subject_inference import infer_subject


def _mock_meta(patient_id=None, patient_name=None):
    m = MagicMock()
    m.patient_id = patient_id
    m.patient_name = patient_name
    return m


def test_patient_id_wins():
    meta = _mock_meta(patient_id="P001", patient_name="John Doe")
    result = infer_subject(meta, Path("/data/sub-999/file.dcm"))
    assert result == "P001"


def test_generic_patient_id_falls_through():
    meta = _mock_meta(patient_id="anonymous", patient_name="Jane")
    result = infer_subject(meta, Path("/data/file.dcm"))
    assert result == "Jane"


def test_path_fallback():
    result = infer_subject(None, Path("/data/sub-042/file.dcm"))
    assert result == "042"


def test_fallback_value():
    result = infer_subject(None, Path("/tmp/file.dcm"), fallback="fallback")
    assert result == "fallback"
