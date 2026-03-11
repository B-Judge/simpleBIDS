"""Build a dcm2bids_config.json from user-labeled series."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from simpleBIDS.patterns.series_grouper import SeriesGroup

logger = logging.getLogger(__name__)


@dataclass
class LabeledSeries:
    """A :class:`SeriesGroup` annotated with user-confirmed BIDS labels."""

    series_group: SeriesGroup
    datatype: str            # e.g. "anat", "func", "dwi"
    suffix: str              # e.g. "T1w", "bold", "dwi"
    entities: dict[str, str] = field(default_factory=dict)  # task, run, dir, etc.
    custom_criteria: dict[str, str] = field(default_factory=dict)  # extra dcm2bids filters
    exclude: bool = False    # True → add to dcm2bids "exclude" list


def build_config(labeled_series: list[LabeledSeries]) -> dict:
    """Build a dcm2bids-compatible config dictionary.

    Args:
        labeled_series: Series annotated by the user in the GUI.

    Returns:
        Dictionary matching the dcm2bids ``config.json`` schema.
        Write it to disk with :func:`write_config`.
    """
    descriptions = []
    for ls in labeled_series:
        if ls.exclude:
            continue

        entry: dict = {
            "datatype": ls.datatype,
            "suffix": ls.suffix,
            "criteria": _build_criteria(ls),
        }

        if ls.entities:
            entry["custom_entities"] = ls.entities

        descriptions.append(entry)

    config = {
        "descriptions": descriptions,
    }
    logger.info("Built config with %d descriptions", len(descriptions))
    return config


def write_config(config: dict, path: Path) -> None:
    """Write *config* as a formatted JSON file.

    Creates parent directories as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    logger.info("Wrote dcm2bids config to %s", path)


def _build_criteria(ls: LabeledSeries) -> dict:
    """Assemble the ``criteria`` block for one series entry."""
    criteria: dict = {}
    group = ls.series_group

    if group.series_description:
        criteria["SeriesDescription"] = group.series_description
    if group.series_number is not None:
        criteria["SeriesNumber"] = group.series_number

    # Extra discriminating fields (e.g. ImageType) passed through from grouper
    image_type = group.extra.get("image_type")
    if image_type:
        criteria["ImageType"] = image_type

    # Any additional user-supplied criteria
    criteria.update(ls.custom_criteria)
    return criteria
