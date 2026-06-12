"""Helpers for cache-safe no-series continuity components."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeRelation

CONTINUITY_RELATION_TYPES = {"prequel", "sequel"}


def get_component_ids(snapshot: AnimeFranchiseSnapshot) -> set[str]:
    """Return media IDs in the snapshot continuity component."""
    return {str(node.media_id) for node in snapshot.continuity_component}


def get_internal_continuity_relations(
    snapshot: AnimeFranchiseSnapshot,
    component_ids: set[str],
) -> list[AnimeRelation]:
    """Return prequel/sequel relations whose endpoints are both in the component."""
    return [
        relation
        for relation in snapshot.all_normalized_relations
        if relation.relation_type in CONTINUITY_RELATION_TYPES
        and relation.source_media_id in component_ids
        and relation.target_media_id in component_ids
    ]


def continuity_direction(
    source_id: str,
    target_id: str,
    relation_type: str,
) -> tuple[str, str]:
    """Orient continuity edges from earlier to later media."""
    if relation_type == "prequel":
        return target_id, source_id
    return source_id, target_id


def order_component_media_ids(
    snapshot: AnimeFranchiseSnapshot,
    component_ids: set[str],
    relations: list[AnimeRelation],
) -> list[str]:
    """Order no-series components from the canonical root, then stable fallbacks."""
    adjacency: dict[str, set[str]] = {media_id: set() for media_id in component_ids}
    for relation in relations:
        source_id, target_id = continuity_direction(
            relation.source_media_id,
            relation.target_media_id,
            relation.relation_type,
        )
        adjacency.setdefault(source_id, set()).add(target_id)

    anchor_id = str(snapshot.canonical_root_media_id or snapshot.root_node.media_id)
    ordered_ids: list[str] = []
    visited: set[str] = set()
    if anchor_id in component_ids:
        queue = deque([anchor_id])
        visited.add(anchor_id)
        while queue:
            current_id = queue.popleft()
            ordered_ids.append(current_id)
            for next_id in sorted(
                adjacency.get(current_id, set()),
                key=lambda media_id: _node_sort_tuple(snapshot, media_id),
            ):
                if next_id in visited:
                    continue
                visited.add(next_id)
                queue.append(next_id)

    ordered_ids.extend(
        sorted(
            component_ids - visited,
            key=lambda media_id: _node_sort_tuple(snapshot, media_id),
        )
    )
    return ordered_ids


def build_component_entries(snapshot: AnimeFranchiseSnapshot) -> list[dict]:
    """Build cache-safe full no-series component entries."""
    component_ids = get_component_ids(snapshot)
    relations = get_internal_continuity_relations(snapshot, component_ids)
    ordered_ids = order_component_media_ids(snapshot, component_ids, relations)
    ranks = {media_id: index for index, media_id in enumerate(ordered_ids)}

    entries: list[dict] = []
    for media_id in ordered_ids:
        node = snapshot.nodes_by_media_id.get(media_id)
        if node is None:
            continue
        entries.append(
            {
                "media_id": str(node.media_id),
                "title": node.title,
                "image": node.image,
                "source": node.source,
                "media_type": "anime",
                "anime_media_type": node.media_type,
                "start_date": node.start_date,
                "runtime_minutes": node.runtime_minutes,
                "episode_count": node.episode_count,
                "section_sort_rank": ranks[media_id],
            }
        )
    return entries


def build_component_relations(snapshot: AnimeFranchiseSnapshot) -> list[dict]:
    """Build cache-safe internal no-series continuity relations."""
    component_ids = get_component_ids(snapshot)
    return [
        {
            "source_media_id": str(relation.source_media_id),
            "target_media_id": str(relation.target_media_id),
            "relation_type": relation.relation_type,
        }
        for relation in get_internal_continuity_relations(snapshot, component_ids)
    ]


def _node_sort_tuple(
    snapshot: AnimeFranchiseSnapshot,
    media_id: str,
) -> tuple[str, str]:
    node = snapshot.nodes_by_media_id.get(media_id)
    date_value = (
        node.start_date.isoformat() if node and node.start_date else "9999-12-31"
    )
    return date_value, str(media_id)
