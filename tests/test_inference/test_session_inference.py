"""Tests for session_inference."""

from pathlib import Path
from unittest.mock import MagicMock

from simpleBIDS.inference.session_inference import infer_session


def _mock_meta(series_date=None, acquisition_date=None, study_date=None):
    m = MagicMock()
    m.series_date = series_date
    m.acquisition_date = acquisition_date
    m.study_date = study_date
    return m


def test_series_date_wins():
    meta = _mock_meta(series_date="20231025", study_date="20231020")
    result = infer_session(meta, Path("/data/file.dcm"))
    assert result == "20231025"


def test_study_date_fallback():
    meta = _mock_meta(study_date="20220101")
    result = infer_session(meta, Path("/data/file.dcm"))
    assert result == "20220101"


def test_path_date_fallback():
    result = infer_session(None, Path("/data/20230415/file.dcm"))
    assert result == "20230415"


def test_keyword_session():
    result = infer_session(None, Path("/data/patient/baseline/file.dcm"))
    assert result == "baseline"


def test_default_fallback():
    result = infer_session(None, Path("/tmp/file.dcm"), fallback="01")
    assert result == "01"
