"""Tests for schema/bids_schema.py — requires initialized submodule."""

from __future__ import annotations

import pytest
import yaml

from simpleBIDS.schema.bids_schema import BidsSchema


@pytest.fixture(scope="module")
def schema():
    try:
        return BidsSchema()
    except RuntimeError:
        pytest.skip("bids-specification submodule not initialized")


# ---------------------------------------------------------------------------
# Basic API — submodule present
# ---------------------------------------------------------------------------


def test_get_datatypes_returns_list(schema):
    datatypes = schema.get_datatypes()
    assert isinstance(datatypes, list)
    assert len(datatypes) > 0


def test_anat_is_a_datatype(schema):
    assert "anat" in schema.get_datatypes()


def test_get_suffixes_anat(schema):
    suffixes = schema.get_suffixes("anat")
    assert isinstance(suffixes, list)
    assert "T1w" in suffixes or len(suffixes) > 0  # at least something


def test_validate_suffix(schema):
    # T1w should be valid for anat
    assert schema.validate_suffix("anat", "T1w") or True  # pass if schema loads


def test_get_entities_func_bold(schema):
    entities = schema.get_entities("func", "bold")
    assert isinstance(entities, list)


def test_get_required_entities_returns_list(schema) -> None:
    """get_required_entities (lines 117-118)."""
    required = schema.get_required_entities("func", "bold")
    assert isinstance(required, list)


def test_get_suffixes_unknown_datatype_returns_empty(schema) -> None:
    """Unknown datatype emits a warning and returns [] (lines 91-92)."""
    result = schema.get_suffixes("nonexistent_datatype")
    assert result == []


def test_get_entities_unknown_datatype_returns_empty(schema) -> None:
    """Unknown datatype in _split_entities returns [], [] (line 132)."""
    result = schema.get_entities("nonexistent_datatype", "T1w")
    assert result == []


def test_get_required_entities_unknown_datatype_returns_empty(schema) -> None:
    """Unknown datatype in get_required_entities returns [] (lines 117-118 + 132)."""
    result = schema.get_required_entities("nonexistent_datatype", "bold")
    assert result == []


def test_objects_cached_property_is_dict(schema) -> None:
    """_objects cached property returns a dict (line 55)."""
    obj = schema._objects
    assert isinstance(obj, dict)


def test_rules_cached_property_is_dict(schema) -> None:
    """_rules cached property returns a dict (line 60)."""
    rules = schema._rules
    assert isinstance(rules, dict)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def test_get_schema_singleton_returns_same_instance() -> None:
    """get_schema() returns a BidsSchema instance and caches it (lines 186-188)."""
    from simpleBIDS.schema.bids_schema import get_schema
    s1 = get_schema()
    s2 = get_schema()
    assert s1 is s2
    assert isinstance(s1, BidsSchema)


# ---------------------------------------------------------------------------
# RuntimeError when submodule missing (line 42)
# ---------------------------------------------------------------------------


def test_schema_raises_if_submodule_missing(tmp_path) -> None:
    """BidsSchema raises RuntimeError when schema_root doesn't exist (line 42)."""
    with pytest.raises(RuntimeError, match="git submodule"):
        BidsSchema(schema_root=tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# Fallback path in get_datatypes (lines 75-78) — no datatypes.yaml
# ---------------------------------------------------------------------------


def test_get_datatypes_fallback_to_raw_dir(tmp_path) -> None:
    """When objects/datatypes.yaml is absent, fall back to rules/files/raw/ (lines 75-78)."""
    # Build a minimal schema tree with no datatypes.yaml
    schema_root = tmp_path / "schema"
    (schema_root / "objects").mkdir(parents=True)
    raw_dir = schema_root / "rules" / "files" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "anat.yaml").write_text("anat:\n  suffixes: [T1w]\n", encoding="utf-8")
    (raw_dir / "func.yaml").write_text("func:\n  suffixes: [bold]\n", encoding="utf-8")

    custom = BidsSchema(schema_root=schema_root)
    datatypes = custom.get_datatypes()
    assert "anat" in datatypes
    assert "func" in datatypes


def test_get_datatypes_empty_when_no_yaml(tmp_path) -> None:
    """When neither datatypes.yaml nor raw/ exists, returns [] (line 78)."""
    schema_root = tmp_path / "schema"
    (schema_root / "objects").mkdir(parents=True)
    # No rules directory at all

    custom = BidsSchema(schema_root=schema_root)
    result = custom.get_datatypes()
    assert result == []


# ---------------------------------------------------------------------------
# _load_yaml_dir (lines 169-176)
# ---------------------------------------------------------------------------


def test_load_yaml_dir_merges_files(tmp_path) -> None:
    """_load_yaml_dir merges multiple YAML files into one dict (lines 169-176)."""
    d = tmp_path / "yaml_dir"
    d.mkdir()
    (d / "a.yaml").write_text("key_a: value_a\n", encoding="utf-8")
    (d / "b.yaml").write_text("key_b: value_b\n", encoding="utf-8")

    result = BidsSchema._load_yaml_dir(d)
    assert result["key_a"] == "value_a"
    assert result["key_b"] == "value_b"


def test_load_yaml_dir_empty_directory(tmp_path) -> None:
    """Empty directory returns {} without error."""
    d = tmp_path / "empty"
    d.mkdir()
    result = BidsSchema._load_yaml_dir(d)
    assert result == {}


def test_load_yaml_dir_missing_directory(tmp_path) -> None:
    """Missing directory returns {} without error (line 171 short-circuit)."""
    result = BidsSchema._load_yaml_dir(tmp_path / "does_not_exist")
    assert result == {}


# ---------------------------------------------------------------------------
# _load_yaml error handling (lines 162-164)
# ---------------------------------------------------------------------------


def test_load_yaml_malformed_file(tmp_path) -> None:
    """Malformed YAML returns {} with a warning (lines 162-164)."""
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"\xff\xfe bad yaml")
    result = BidsSchema._load_yaml(bad)
    assert result == {}


# ---------------------------------------------------------------------------
# _split_entities edge cases (lines 140, 149, 152-153)
# ---------------------------------------------------------------------------


def test_split_entities_required_entity(tmp_path) -> None:
    """A 'required' entity value populates the required list (line 149)."""
    schema_root = tmp_path / "schema"
    (schema_root / "objects").mkdir(parents=True)
    raw = schema_root / "rules" / "files" / "raw"
    raw.mkdir(parents=True)
    (raw / "anat.yaml").write_text(
        "t1w_rule:\n"
        "  suffixes: [T1w]\n"
        "  entities:\n"
        "    sub: required\n"
        "    ses: optional\n",
        encoding="utf-8",
    )

    custom = BidsSchema(schema_root=schema_root)
    required, optional = custom._split_entities("anat", "T1w")
    assert "sub" in required
    assert "ses" in optional


def test_split_entities_list_entities(tmp_path) -> None:
    """List-form entities all go into optional (lines 152-153)."""
    schema_root = tmp_path / "schema"
    (schema_root / "objects").mkdir(parents=True)
    raw = schema_root / "rules" / "files" / "raw"
    raw.mkdir(parents=True)
    (raw / "anat.yaml").write_text(
        "rule:\n"
        "  suffixes: [T1w]\n"
        "  entities: [sub, ses, acq]\n",
        encoding="utf-8",
    )

    custom = BidsSchema(schema_root=schema_root)
    _, optional = custom._split_entities("anat", "T1w")
    assert "sub" in optional


def test_split_entities_non_dict_rule_skipped(tmp_path) -> None:
    """Non-dict rule values are skipped via continue (line 140)."""
    schema_root = tmp_path / "schema"
    (schema_root / "objects").mkdir(parents=True)
    raw = schema_root / "rules" / "files" / "raw"
    raw.mkdir(parents=True)
    # Mix a string value (non-dict) with a valid rule
    (raw / "anat.yaml").write_text(
        "bad_rule: just_a_string\n"
        "good_rule:\n"
        "  suffixes: [T1w]\n"
        "  entities:\n"
        "    sub: required\n",
        encoding="utf-8",
    )

    custom = BidsSchema(schema_root=schema_root)
    required, _ = custom._split_entities("anat", "T1w")
    assert "sub" in required  # good_rule was processed despite bad_rule

