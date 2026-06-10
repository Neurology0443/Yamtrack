"""Lightweight first-visit MAL anime franchise fallback payload builder."""

from __future__ import annotations

import logging

from django.conf import settings

from app.providers import mal
from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService

logger = logging.getLogger(__name__)

_CONTINUITY_RELATIONS = {"prequel", "sequel"}
_FALLBACK_HARD_MAX_NODES = 30
_MIN_DISPLAYABLE_SERIES_ENTRIES = 2


def _get_fallback_max_nodes() -> int:
    """Return the bounded synchronous fallback node limit."""
    configured = settings.ANIME_FRANCHISE_FALLBACK_MAX_NODES
    if configured <= 0:
        return 0
    return min(configured, _FALLBACK_HARD_MAX_NODES)


def _fallback_metadata_fetcher(media_id, *, refresh_cache=False):
    """Fetch fallback metadata without forcing/scheduling MAL refreshes."""
    return mal.anime(
        str(media_id),
        refresh_cache=refresh_cache,
        allow_stale=True,
        schedule_stale_refresh=False,
    )


def get_related_anime(media_metadata: dict) -> list:
    """Return direct MAL related anime entries when provider shape is valid."""
    related = media_metadata.get("related")
    if not isinstance(related, dict):
        return []

    related_anime = related.get("related_anime", [])
    if not isinstance(related_anime, list):
        return []

    return related_anime


def _normalize_relation_type_safely(raw_relation_type) -> str:
    """Normalize relation types while ignoring unexpected provider values."""
    if not isinstance(raw_relation_type, str):
        return ""
    return mal.normalize_relation_type(raw_relation_type)


def has_direct_continuity_relation(media_metadata: dict) -> bool:
    """Return whether metadata directly references a prequel or sequel."""
    for relation in get_related_anime(media_metadata):
        if not isinstance(relation, dict):
            continue
        relation_type = _normalize_relation_type_safely(
            relation.get("relation_type"),
        )
        if relation_type in _CONTINUITY_RELATIONS:
            return True

    return False


def _node_to_entry(node) -> dict:
    """Convert a snapshot node to a user-agnostic template entry."""
    return {
        "media_id": str(node.media_id),
        "source": node.source,
        "media_type": "anime",
        "anime_media_type": node.media_type or "",
        "title": node.title,
        "image": node.image,
        "start_date": node.start_date.isoformat() if node.start_date else None,
        "runtime_minutes": node.runtime_minutes,
        "episode_count": node.episode_count,
        "relation_type": None,
        "is_current": False,
    }


def build_series_line_fallback_payload(media_id, media_metadata: dict) -> dict | None:
    """Build a bounded, temporary TV series-line payload for first cache miss."""
    if not settings.ANIME_FRANCHISE_FALLBACK_ENABLED:
        return None

    fallback_max_nodes = _get_fallback_max_nodes()
    if fallback_max_nodes <= 0:
        return None

    if not has_direct_continuity_relation(media_metadata):
        return None

    try:
        graph_builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=_fallback_metadata_fetcher,
            max_nodes=fallback_max_nodes,
        )
        snapshot = AnimeFranchiseSnapshotService(graph_builder=graph_builder).build(
            str(media_id),
        )
        series_line = snapshot.series_line
        if len(series_line) < _MIN_DISPLAYABLE_SERIES_ENTRIES:
            return None

        entries = [_node_to_entry(node) for node in series_line]
        for entry in entries:
            entry["is_current"] = str(entry["media_id"]) == str(media_id)

        return {
            "root_media_id": str(media_id),
            "display_title": media_metadata.get("title") or snapshot.root_node.title,
            "series": {
                "key": AnimeFranchiseService.SERIES_LINE_KEY,
                "title": "Series",
                "entries": entries,
            },
            "sections": [],
            "truncated": bool(graph_builder.is_truncated),
            "fallback": True,
        }
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to build MAL anime franchise series-line fallback for media_id=%s",
            media_id,
            exc_info=True,
        )
        return None
