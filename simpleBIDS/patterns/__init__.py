"""Series grouping, slice sampling, and symlink staging."""

from simpleBIDS.patterns.series_grouper import SeriesGroup, group_series
from simpleBIDS.patterns.symlink_sorter import build_staging, cleanup_staging
from simpleBIDS.patterns.slice_sampler import sample_slice

__all__ = [
    "SeriesGroup",
    "group_series",
    "build_staging",
    "cleanup_staging",
    "sample_slice",
]
