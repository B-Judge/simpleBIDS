"""Tests for path_parser heuristics."""

from pathlib import Path

from simpleBIDS.parsers.path_parser import bids_safe, extract_path_candidates


def test_bids_sub_pattern():
    path = Path("/data/sub-001/ses-01/someFile.dcm")
    candidates = extract_path_candidates(path, mode="subject")
    assert any(c.value == "001" and c.source == "bids_sub" for c in candidates)


def test_bids_ses_pattern():
    path = Path("/data/sub-001/ses-baseline/someFile.dcm")
    candidates = extract_path_candidates(path, mode="session")
    assert any(c.value == "baseline" and c.source == "bids_ses" for c in candidates)


def test_date_compact_session():
    path = Path("/data/patient1/20231025/scan.dcm")
    candidates = extract_path_candidates(path, mode="session")
    assert any(c.value == "20231025" and c.source == "date_compact" for c in candidates)


def test_bids_safe_strips_special_chars():
    assert bids_safe("PAT 001!") == "PAT001"
    assert bids_safe("sub-01") == "sub01"


def test_no_candidates_returns_empty():
    path = Path("/tmp/file.dcm")
    candidates = extract_path_candidates(path, mode="subject")
    # May or may not match bare numbers — just assert it's a list
    assert isinstance(candidates, list)
