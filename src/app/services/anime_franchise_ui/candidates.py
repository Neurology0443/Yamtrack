"""Core UI candidate types for anime franchise secondary sections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class UiCandidate:
    """Secondary UI candidate derived from snapshot entries outside `Series`."""

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
    is_current: bool = False
    section_key: str | None = None
    hidden: bool = False
    badges: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
