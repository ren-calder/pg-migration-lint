"""Shared types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RawFinding:
    """A finding before it is mapped to a line and column."""

    rule: str
    offset: int  # character offset into the decoded file text
    message: str
