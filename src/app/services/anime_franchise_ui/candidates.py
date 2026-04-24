"""Core candidate datatypes for secondary franchise UI sections.

This module only models data prepared for downstream rules/layout. It does not
decide final section placement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class UiCandidate:
    """Secondary UI candidate derived from snapshot entries outside `Series`.

    `relation_type` is a convenience facade using one representative relation.
    For ambiguous candidates, rules should prefer richer signals in
    `relation_types` and `metadata["origins"]`.
    """

    media_id: str
    title: str
    image: str
    source: str
    media_type: str
    relation_type: str
    start_date: date | None
    runtime_minutes: int | None
    episode_count: int | None
    linked_series_line_media_id: str | None
    linked_series_line_index: int | None
    linked_root_media_id: str | None = None
    relation_types: list[str] = field(default_factory=list)
    source_media_ids: list[str] = field(default_factory=list)
    has_series_line_origin: bool = False
    has_root_origin: bool = False
    has_non_series_origin: bool = False
    is_light: bool = False
    route_media_type: str = "anime"
    is_current: bool = False
    section_key: str | None = None
    hidden: bool = False
    badges: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
