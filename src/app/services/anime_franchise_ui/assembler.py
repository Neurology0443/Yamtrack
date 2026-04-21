"""Snapshot -> UiCandidate assembler for secondary franchise entries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .candidates import UiCandidate

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


class UiCandidateAssembler:
    """Build canonical secondary candidates while keeping Series separate."""

    def build(self, snapshot: AnimeFranchiseSnapshot) -> list[UiCandidate]:
        series_ids = {node.media_id for node in snapshot.series_line}
        series_index = {node.media_id: idx for idx, node in enumerate(snapshot.series_line)}

        candidates_by_media_id: dict[str, UiCandidate] = {}
        for relation in snapshot.direct_candidates:
            if relation.target_media_id in series_ids:
                continue

            node = snapshot.nodes_by_media_id.get(relation.target_media_id)
            if node is None:
                continue

            linked_id = (
                relation.source_media_id
                if relation.source_media_id in series_ids
                else None
            )

            existing = candidates_by_media_id.get(node.media_id)
            if existing is not None:
                if linked_id and existing.linked_series_line_media_id is None:
                    existing.linked_series_line_media_id = linked_id
                    existing.linked_series_line_index = series_index.get(linked_id)
                continue

            candidates_by_media_id[node.media_id] = UiCandidate(
                media_id=node.media_id,
                title=node.title,
                image=node.image,
                source=node.source,
                media_type=node.media_type,
                relation_type=relation.relation_type,
                start_date=node.start_date,
                runtime_minutes=node.runtime_minutes,
                episode_count=node.episode_count,
                linked_series_line_media_id=linked_id,
                linked_series_line_index=series_index.get(linked_id),
                is_current=node.media_id == snapshot.root_node.media_id,
                metadata={"source_relation": relation.relation_type},
            )

        return list(candidates_by_media_id.values())
