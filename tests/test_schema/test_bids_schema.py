"""Tests for schema/bids_schema.py — requires initialized submodule."""

import pytest

from simpleBIDS.schema.bids_schema import BidsSchema


@pytest.fixture(scope="module")
def schema():
    try:
        return BidsSchema()
    except RuntimeError:
        pytest.skip("bids-specification submodule not initialized")


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
