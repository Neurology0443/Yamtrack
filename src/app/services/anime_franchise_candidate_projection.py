"""Shared candidate projection from franchise snapshot data."""

from __future__ import annotations

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeFranchiseCandidate


def build_franchise_candidates(snapshot: AnimeFranchiseSnapshot) -> dict[str, AnimeFranchiseCandidate]:
    """Build canonical franchise candidates keyed by media id.

    The projection keeps only the best direct candidate per media id, using the
    same ordering semantics as the historical UI builder implementation.
    """

    candidates: dict[str, AnimeFranchiseCandidate] = {}
    series_line_ids = {node.media_id for node in snapshot.series_line}
    line_index_map = {node.media_id: idx for idx, node in enumerate(snapshot.series_line)}

    for relation in snapshot.direct_candidates:
        target_id = relation.target_media_id
        if target_id in series_line_ids:
            continue

        target_node = snapshot.nodes_by_media_id[target_id]
        linked_id = relation.source_media_id if snapshot.has_series_line else snapshot.fallback_anchor_media_id
        candidate = AnimeFranchiseCandidate(
            media_id=target_node.media_id,
            title=target_node.title,
            image=target_node.image,
            source=target_node.source,
            media_type=target_node.media_type,
            start_date=target_node.start_date,
            relation_type=relation.relation_type,
            is_current=target_node.media_id == snapshot.root_node.media_id,
            is_direct_from_series_line=True,
            linked_series_line_media_id=linked_id,
            linked_series_line_index=(line_index_map.get(linked_id) if snapshot.has_series_line else 0),
            runtime_minutes=target_node.runtime_minutes,
            episode_count=target_node.episode_count,
        )
        existing = candidates.get(candidate.media_id)
        if existing is None or _candidate_sort_key(candidate) < _candidate_sort_key(existing):
            candidates[candidate.media_id] = candidate

    return candidates


def _candidate_sort_key(candidate: AnimeFranchiseCandidate) -> tuple:
    """Mirror historical builder ordering for deterministic best-candidate selection.

    This intentionally mirrors the legacy candidate replacement behavior from
    the pre-refactor UI builder so projection outputs stay functionally
    identical.
    """

    linked_index = candidate.linked_series_line_index if candidate.linked_series_line_index is not None else 10_000
    relation_rank = 0 if candidate.relation_type == "prequel" else 1
    return (linked_index, relation_rank, _date_value(candidate.start_date), int(candidate.media_id))


def _date_value(start_date) -> str:
    return start_date.isoformat() if start_date else "9999-12-31"
