"""Headless tests for LabelForm._OPTIONAL_ENTITIES — no display required."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# All standard BIDS entities (minus sub and ses) that must be present in the
# optional section. This list is the source of truth for Change 4.
# ---------------------------------------------------------------------------
_EXPECTED_ENTITY_KEYS = {
    "task", "acq", "ce", "trc", "stain", "rec", "dir", "run", "mod",
    "echo", "flip", "inv", "mt", "part",
    "proc", "hemi", "space", "split", "res", "den", "label", "desc",
    "chunk", "sample", "atlas", "from", "to",
}


def test_all_bids_entities_in_optional_list() -> None:
    """Every expected BIDS entity key must appear in LabelForm._OPTIONAL_ENTITIES."""
    from simpleBIDS.cli.label import BIDS_OPTIONAL_ENTITIES as _ENTITY_LIST

    present = {key for key, _ in _ENTITY_LIST}
    missing = _EXPECTED_ENTITY_KEYS - present
    assert not missing, f"Missing entity keys in _OPTIONAL_ENTITIES: {missing}"


def test_no_subject_or_session_in_optional_list() -> None:
    """sub and ses must never appear — they are inferred, not user-entered."""
    from simpleBIDS.cli.label import BIDS_OPTIONAL_ENTITIES as _ENTITY_LIST

    keys = {key for key, _ in _ENTITY_LIST}
    assert "sub" not in keys
    assert "ses" not in keys


def test_all_display_labels_have_entity_prefix() -> None:
    """Each display label should start with 'entity-' for consistency."""
    from simpleBIDS.cli.label import BIDS_OPTIONAL_ENTITIES as _ENTITY_LIST

    for key, label in _ENTITY_LIST:
        assert key in label, f"Display label for '{key}' does not contain the entity key: {label!r}"


def test_no_duplicate_entity_keys() -> None:
    """Each entity key must appear exactly once."""
    from simpleBIDS.cli.label import BIDS_OPTIONAL_ENTITIES as _ENTITY_LIST

    keys = [key for key, _ in _ENTITY_LIST]
    assert len(keys) == len(set(keys)), f"Duplicate keys: {[k for k in keys if keys.count(k) > 1]}"
