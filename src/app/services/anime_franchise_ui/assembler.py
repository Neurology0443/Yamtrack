"""Assemble canonical secondary `UiCandidate` objects from a snapshot.

Responsibilities:
- exclude fixed `Series` entries
- deduplicate by target media id
- preserve origin signals (relation types, source ids, anchor hints) for rules

Non-responsibilities:
- no business ranking between relation types
- no section decision logic
"""

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
        root_media_id = snapshot.root_node.media_id

        grouped_relations: dict[str, list] = {}
        for relation in snapshot.direct_candidates:
            if relation.target_media_id in series_ids:
                continue
            grouped_relations.setdefault(relation.target_media_id, []).append(relation)

        candidates: list[UiCandidate] = []
        for target_media_id, relations in grouped_relations.items():
            node = snapshot.nodes_by_media_id.get(target_media_id)
            if node is None:
                continue

            relation_types = self._ordered_unique([relation.relation_type for relation in relations])
            source_media_ids = self._ordered_unique([relation.source_media_id for relation in relations])
            series_line_sources = [source_id for source_id in source_media_ids if source_id in series_ids]
            root_sources = [source_id for source_id in source_media_ids if source_id == root_media_id]
            non_series_sources = [
                source_id for source_id in source_media_ids if source_id not in series_ids
            ]

            linked_series_line_media_id = self._pick_series_anchor(series_line_sources, series_index)
            linked_root_media_id = root_media_id if root_sources else None

            candidates.append(
                UiCandidate(
                media_id=node.media_id,
                title=node.title,
                image=node.image,
                source=node.source,
                media_type=node.media_type,
                relation_type=relation_types[0] if relation_types else "unknown",
                start_date=node.start_date,
                runtime_minutes=node.runtime_minutes,
                episode_count=node.episode_count,
                linked_series_line_media_id=linked_series_line_media_id,
                linked_series_line_index=(
                    series_index.get(linked_series_line_media_id)
                    if linked_series_line_media_id
                    else None
                ),
                linked_root_media_id=linked_root_media_id,
                relation_types=relation_types,
                source_media_ids=source_media_ids,
                has_series_line_origin=bool(series_line_sources),
                has_root_origin=bool(root_sources),
                has_non_series_origin=bool(non_series_sources),
                is_current=node.media_id == snapshot.root_node.media_id,
                metadata={
                    "origins": [
                        {
                            "source_media_id": relation.source_media_id,
                            "relation_type": relation.relation_type,
                            "is_from_series_line": relation.source_media_id in series_ids,
                            "is_from_root_node": relation.source_media_id == root_media_id,
                        }
                        for relation in relations
                    ],
                },
            )
            )

        return candidates

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _pick_series_anchor(
        series_line_sources: list[str],
        series_index: dict[str, int],
    ) -> str | None:
        if not series_line_sources:
            return None
        return min(
            series_line_sources,
            key=lambda media_id: series_index.get(media_id, 999999),
        )
