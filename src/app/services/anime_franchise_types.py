"""Types used by the MAL anime franchise grouping service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date


@dataclass(frozen=True)
class AnimeRelation:
    """A normalized edge between two MAL anime entries."""

    source_media_id: str
    target_media_id: str
    relation_type: str
    target_title: str | None = None
    target_image: str | None = None
    target_source: str | None = None
    target_route_media_type: str | None = None


@dataclass
class AnimeNode:
    """Normalized MAL anime metadata used by the grouping engine."""

    media_id: str
    title: str
    source: str
    media_type: str
    image: str
    start_date: date | None
    relations: list[AnimeRelation] = field(default_factory=list)
    runtime_minutes: int | None = None
    episode_count: int | None = None


@dataclass
class AnimeFranchiseCandidate:
    """Candidate entry that can be matched to a display section."""

    media_id: str
    title: str
    image: str
    source: str
    media_type: str
    start_date: date | None
    relation_type: str
    is_current: bool
    is_direct_from_series_line: bool
    linked_series_line_media_id: str | None
    linked_series_line_index: int | None


@dataclass(frozen=True)
class AnimeFranchiseSectionRule:
    """Rule-based descriptor for one grouped section."""

    key: str
    title: str
    visible_in_ui: bool
    priority: int
    include_relation_types: frozenset[str] = field(default_factory=frozenset)
    exclude_relation_types: frozenset[str] = field(default_factory=frozenset)
    include_media_types: frozenset[str] = field(default_factory=frozenset)
    exclude_media_types: frozenset[str] = field(default_factory=frozenset)
    direct_from_series_line_only: bool = False
    allow_indirect_candidates: bool = True
    sort_mode: str = "default"
    show_relation_badge: bool = False
    show_media_type_badge: bool = False
    hidden_if_empty: bool = True
    predicate: Callable[[AnimeFranchiseCandidate], bool] | None = None


@dataclass
class AnimeFranchiseSectionView:
    """UI-ready section payload for rendering."""

    key: str
    title: str
    entries: list[dict]
    visible_in_ui: bool
    hidden_if_empty: bool


@dataclass
class AnimeFranchiseViewModel:
    """Top-level view model consumed by the anime details template."""

    root_media_id: str
    display_title: str
    series_line_entries: list[dict]
    sections: list[AnimeFranchiseSectionView]
