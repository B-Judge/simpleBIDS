"""Load and query the BIDS schema from the bundled git submodule.

The schema lives at ``bids-specification/src/schema/`` relative to the
repository root. It is parsed once and cached for the lifetime of the process.

All BIDS naming decisions in the codebase must go through this module —
never hardcode datatypes, suffixes, or entity lists elsewhere.
"""

from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Path from this file up to the repo root, then into the submodule
_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMA_ROOT = _REPO_ROOT / "bids-specification" / "src" / "schema"


class BidsSchema:
    """Lazy-loading accessor for the BIDS machine-readable schema.

    Usage::

        schema = BidsSchema()
        schema.get_datatypes()          # ['anat', 'func', 'dwi', ...]
        schema.get_suffixes('anat')     # ['T1w', 'T2w', 'FLAIR', ...]
        schema.get_entities('func', 'bold')  # ['sub', 'ses', 'task', 'run', ...]
    """

    def __init__(self, schema_root: Path | None = None) -> None:
        self._schema_root = schema_root or _SCHEMA_ROOT
        self._validate_submodule()

    def _validate_submodule(self) -> None:
        if not self._schema_root.exists():
            raise RuntimeError(
                f"BIDS schema not found at {self._schema_root}.\n"
                "Initialize the submodule with:\n"
                "  git submodule update --init"
            )

    # ------------------------------------------------------------------
    # Raw schema data (cached)
    # ------------------------------------------------------------------

    @cached_property
    def _objects(self) -> dict:
        """Top-level 'objects' from the schema (datatypes, suffixes, entities)."""
        return self._load_yaml_dir(self._schema_root / "objects")

    @cached_property
    def _rules(self) -> dict:
        """Top-level 'rules' from the schema."""
        return self._load_yaml_dir(self._schema_root / "rules")

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_datatypes(self) -> list[str]:
        """Return all valid BIDS datatype folder names (e.g. ``anat``, ``func``)."""
        # Primary: objects/datatypes.yaml — keys are the canonical datatype names
        datatypes_file = self._schema_root / "objects" / "datatypes.yaml"
        if datatypes_file.exists():
            data = self._load_yaml(datatypes_file)
            if data:
                return sorted(data.keys())
        # Fallback: rules/files/raw/ directory — one YAML per datatype
        raw_path = self._schema_root / "rules" / "files" / "raw"
        if raw_path.exists():
            return sorted(p.stem for p in raw_path.iterdir() if p.suffix in {".yaml", ".yml"})
        return []

    def get_suffixes(self, datatype: str) -> list[str]:
        """Return all valid suffixes for a given datatype.

        Args:
            datatype: BIDS datatype folder name (e.g. ``"anat"``).

        Returns:
            Sorted list of suffix strings (e.g. ``["T1w", "T2w", "FLAIR"]``).
        """
        datatype_file = self._schema_root / "rules" / "files" / "raw" / f"{datatype}.yaml"
        if not datatype_file.exists():
            logger.warning("No schema file for datatype '%s'", datatype)
            return []

        data = self._load_yaml(datatype_file)
        suffixes: set[str] = set()
        for rule in data.values() if isinstance(data, dict) else []:
            if isinstance(rule, dict):
                for s in rule.get("suffixes", []):
                    suffixes.add(s)
        return sorted(suffixes)

    def get_entities(self, datatype: str, suffix: str) -> list[str]:
        """Return all valid entity keys for a datatype+suffix combination.

        Args:
            datatype: BIDS datatype (e.g. ``"func"``).
            suffix: BIDS suffix (e.g. ``"bold"``).

        Returns:
            List of entity keys (e.g. ``["sub", "ses", "task", "run"]``).
        """
        required, optional = self._split_entities(datatype, suffix)
        return required + [e for e in optional if e not in required]

    def get_required_entities(self, datatype: str, suffix: str) -> list[str]:
        """Return only the *required* entity keys for a datatype+suffix."""
        required, _ = self._split_entities(datatype, suffix)
        return required

    def validate_suffix(self, datatype: str, suffix: str) -> bool:
        """Return True if *suffix* is valid for *datatype* per the schema."""
        return suffix in self.get_suffixes(datatype)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _split_entities(self, datatype: str, suffix: str) -> tuple[list[str], list[str]]:
        """Return (required_entities, optional_entities) for a datatype+suffix."""
        datatype_file = self._schema_root / "rules" / "files" / "raw" / f"{datatype}.yaml"
        if not datatype_file.exists():
            return [], []

        data = self._load_yaml(datatype_file)
        required: list[str] = []
        optional: list[str] = []

        for rule in data.values() if isinstance(data, dict) else []:
            if not isinstance(rule, dict):
                continue
            if suffix not in rule.get("suffixes", []):
                continue
            entities = rule.get("entities", {})
            if isinstance(entities, dict):
                for entity, req in entities.items():
                    if entity == "$ref":
                        continue  # template reference, not a literal entity
                    if req in {"required", True}:
                        required.append(entity)
                    elif req not in {None, "null"}:
                        optional.append(entity)
            elif isinstance(entities, list):
                optional.extend(entities)

        return required, optional

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        try:
            with path.open(encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Failed to parse schema file %s: %s", path, exc)
            return {}

    @staticmethod
    def _load_yaml_dir(directory: Path) -> dict:
        """Recursively merge all YAML files in *directory* into one dict."""
        merged: dict = {}
        if not directory.exists():
            return merged
        for path in sorted(directory.rglob("*.yaml")):
            data = BidsSchema._load_yaml(path)
            if isinstance(data, dict):
                merged.update(data)
        return merged


# Module-level singleton — lazy, instantiated on first import
_schema: BidsSchema | None = None


def get_schema() -> BidsSchema:
    """Return the module-level :class:`BidsSchema` singleton."""
    global _schema
    if _schema is None:
        _schema = BidsSchema()
    return _schema
