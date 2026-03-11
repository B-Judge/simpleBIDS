"""Regex-based heuristics for extracting subject/session hints from file paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Ordered patterns: higher index → higher confidence
_SUBJECT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("bids_sub", re.compile(r"(?i)\bsub[-_]([A-Za-z0-9]+)\b")),
    ("prefixed_id", re.compile(r"(?i)\b(?:PAT|S|ID|SUBJ)[-_]?(\d{2,})\b")),
    ("bare_number", re.compile(r"(?<![0-9])(\d{3,6})(?![0-9])")),
]

_SESSION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("bids_ses", re.compile(r"(?i)\bses[-_]([A-Za-z0-9]+)\b")),
    ("date_dashed", re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")),
    ("date_compact", re.compile(r"\b(20\d{6})\b")),
    ("keyword", re.compile(r"(?i)\b(baseline|followup|follow.up|visit\d+|v\d+|tp\d+|timepoint\d*)\b")),
]


@dataclass
class PathCandidate:
    """A candidate subject or session identifier extracted from a path."""

    value: str
    source: str      # pattern name that matched
    confidence: int  # 0 (low) → 10 (high)
    matched_part: str  # the portion of the path that matched


def extract_path_candidates(
    path: Path,
    *,
    mode: str,  # "subject" or "session"
) -> list[PathCandidate]:
    """Extract ordered candidate identifiers from a file path string.

    Searches all path components (not just the filename). Returns candidates
    sorted descending by confidence. Callers should take the first item, or
    present all options for user selection.

    Args:
        path: File or directory path to examine.
        mode: ``"subject"`` or ``"session"``.

    Returns:
        List of :class:`PathCandidate`, highest confidence first.
        Empty list if no candidates found.
    """
    patterns = _SUBJECT_PATTERNS if mode == "subject" else _SESSION_PATTERNS
    path_str = str(path)
    candidates: list[PathCandidate] = []

    n = len(patterns)
    for idx, (name, pattern) in enumerate(patterns):
        # First pattern in list is most specific → highest confidence
        confidence = n - idx
        for match in pattern.finditer(path_str):
            candidates.append(
                PathCandidate(
                    value=match.group(1),
                    source=name,
                    confidence=confidence,
                    matched_part=match.group(0),
                )
            )

    # Deduplicate by value, keeping highest confidence
    seen: dict[str, PathCandidate] = {}
    for c in candidates:
        if c.value not in seen or c.confidence > seen[c.value].confidence:
            seen[c.value] = c

    return sorted(seen.values(), key=lambda c: c.confidence, reverse=True)


def bids_safe(value: str) -> str:
    """Normalize a string to a BIDS-safe label (alphanumeric only, no spaces)."""
    return re.sub(r"[^A-Za-z0-9]", "", value)
