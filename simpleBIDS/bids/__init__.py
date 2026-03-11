"""BIDS project scaffolding, participants tracking, config building, and conversion."""

from simpleBIDS.bids.scaffold import scaffold_bids
from simpleBIDS.bids.participants import ParticipantsTable
from simpleBIDS.bids.config_builder import LabeledSeries, build_config
from simpleBIDS.bids.converter import convert_subject

__all__ = [
    "scaffold_bids",
    "ParticipantsTable",
    "LabeledSeries",
    "build_config",
    "convert_subject",
]
