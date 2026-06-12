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

from collections import deque
from typing import TYPE_CHECKING

from .candidates import UiCandidate
from .no_series_continuity import (
    CONTINUITY_RELATION_TYPES,
    get_component_ids,
    get_internal_continuity_relations,
    order_component_media_ids,
)

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeRelation


class UiCandidateAssembler:
    """Build canonical secondary candidates while keeping Series separate."""

    def build(self, snapshot: AnimeFranchiseSnapshot) -> list[UiCandidate]:
        series_ids = {node.media_id for node in snapshot.series_line}
        series_index = {
            node.media_id: idx for idx, node in enumerate(snapshot.series_line)
        }
        root_media_id = snapshot.root_node.media_id

        promoted_relations = snapshot.promoted_continuity_candidates or []
        promoted_relation_keys = {
            (relation.source_media_id, relation.target_media_id, relation.relation_type)
            for relation in promoted_relations
        }
        promoted_target_metadata = self._derive_promoted_target_metadata(
            promoted_relations=promoted_relations,
            series_ids=series_ids,
            series_index=series_index,
        )

        grouped_relations: dict[str, list[AnimeRelation]] = {}
        seen_relations: set[tuple[str, str, str]] = set()
        if snapshot.has_series_line:
            for relation in [*snapshot.direct_candidates, *promoted_relations]:
                self._add_grouped_relation(
                    grouped_relations=grouped_relations,
                    seen_relations=seen_relations,
                    relation=relation,
                    series_ids=series_ids,
                )

        mini_relation_keys: set[tuple[str, str, str]] = set()
        mini_sort_ranks: dict[str, int] = {}
        if not snapshot.has_series_line:
            component_ids = get_component_ids(snapshot)
            mini_relation_keys, mini_sort_ranks = (
                self._build_no_series_continuity_candidates(
                    snapshot=snapshot,
                    grouped_relations=grouped_relations,
                    seen_relations=seen_relations,
                    series_ids=series_ids,
                    component_ids=component_ids,
                )
            )
            self._add_no_series_direct_informative_candidates(
                snapshot=snapshot,
                grouped_relations=grouped_relations,
                seen_relations=seen_relations,
                series_ids=series_ids,
                component_ids=component_ids,
            )

        candidates: list[UiCandidate] = []
        for target_media_id, relations in grouped_relations.items():
            node = snapshot.nodes_by_media_id.get(target_media_id)
            if node is None:
                continue

            relation_types = self._ordered_unique(
                [relation.relation_type for relation in relations]
            )
            source_media_ids = self._ordered_unique(
                [relation.source_media_id for relation in relations]
            )
            series_line_sources = [
                source_id for source_id in source_media_ids if source_id in series_ids
            ]
            root_sources = [
                source_id
                for source_id in source_media_ids
                if source_id == root_media_id
            ]
            non_series_sources = [
                source_id
                for source_id in source_media_ids
                if source_id not in series_ids
            ]

            promoted_metadata = promoted_target_metadata.get(target_media_id, {})
            linked_series_line_media_id = self._resolve_best_series_anchor(
                series_line_sources=series_line_sources,
                series_index=series_index,
                promoted_anchor_media_id=promoted_metadata.get(
                    "series_anchor_media_id"
                ),
                promoted_depth=promoted_metadata.get("depth"),
            )
            if linked_series_line_media_id is None and not snapshot.has_series_line:
                linked_series_line_media_id = snapshot.fallback_anchor_media_id
            linked_root_media_id = root_media_id if root_sources else None
            is_promoted_continuity = any(
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                in promoted_relation_keys
                for relation in relations
            )
            is_mini_continuity = any(
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                in mini_relation_keys
                for relation in relations
            )
            metadata = {
                "is_promoted_continuity": is_promoted_continuity,
                "promoted_from_series_line_media_id": promoted_metadata.get(
                    "series_anchor_media_id"
                ),
                "promoted_depth": promoted_metadata.get("depth"),
                "is_mini_continuity": is_mini_continuity,
                "origins": [
                    {
                        "source_media_id": relation.source_media_id,
                        "relation_type": relation.relation_type,
                        "is_from_series_line": relation.source_media_id in series_ids,
                        "is_from_root_node": relation.source_media_id == root_media_id,
                    }
                    for relation in relations
                ],
            }
            if target_media_id in mini_sort_ranks:
                metadata["section_sort_rank"] = mini_sort_ranks[target_media_id]

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
                        series_index.get(linked_series_line_media_id, 0)
                        if linked_series_line_media_id is not None
                        else None
                    ),
                    linked_root_media_id=linked_root_media_id,
                    relation_types=relation_types,
                    source_media_ids=source_media_ids,
                    has_series_line_origin=bool(series_line_sources),
                    has_root_origin=bool(root_sources),
                    has_non_series_origin=bool(non_series_sources),
                    is_current=node.media_id == snapshot.root_node.media_id,
                    metadata=metadata,
                )
            )

        return candidates

    def _build_no_series_continuity_candidates(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        grouped_relations: dict[str, list[AnimeRelation]],
        seen_relations: set[tuple[str, str, str]],
        series_ids: set[str],
        component_ids: set[str],
    ) -> tuple[set[tuple[str, str, str]], dict[str, int]]:
        """Enrich no-series snapshots with the full prequel/sequel component."""
        root_media_id = snapshot.root_node.media_id
        mini_relation_keys: set[tuple[str, str, str]] = set()
        internal_relations = get_internal_continuity_relations(snapshot, component_ids)

        for relation in internal_relations:
            relation_key = (
                relation.source_media_id,
                relation.target_media_id,
                relation.relation_type,
            )
            mini_relation_keys.add(relation_key)
            if relation.target_media_id == root_media_id:
                continue
            self._add_grouped_relation(
                grouped_relations=grouped_relations,
                seen_relations=seen_relations,
                relation=relation,
                series_ids=series_ids,
            )

        for node in snapshot.continuity_component:
            if node.media_id == root_media_id:
                continue
            node_relations = grouped_relations.setdefault(node.media_id, [])
            if node_relations:
                continue
            node_relations.extend(
                relation
                for relation in internal_relations
                if relation.source_media_id == node.media_id
                or relation.target_media_id == node.media_id
            )

        return mini_relation_keys, self._rank_no_series_continuity(
            snapshot=snapshot,
            component_ids=component_ids,
            internal_relations=internal_relations,
        )

    def _add_no_series_direct_informative_candidates(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        grouped_relations: dict[str, list[AnimeRelation]],
        seen_relations: set[tuple[str, str, str]],
        series_ids: set[str],
        component_ids: set[str],
    ) -> None:
        """Add only root-direct non-continuity relations for no-series snapshots."""
        root_media_id = snapshot.root_node.media_id
        for relation in snapshot.direct_candidates:
            if relation.relation_type in CONTINUITY_RELATION_TYPES:
                continue
            if relation.target_media_id == root_media_id:
                continue
            if relation.target_media_id in component_ids:
                continue
            if relation.target_media_id not in snapshot.nodes_by_media_id:
                continue
            self._add_grouped_relation(
                grouped_relations=grouped_relations,
                seen_relations=seen_relations,
                relation=relation,
                series_ids=series_ids,
            )

    @staticmethod
    def _add_grouped_relation(
        *,
        grouped_relations: dict[str, list[AnimeRelation]],
        seen_relations: set[tuple[str, str, str]],
        relation: AnimeRelation,
        series_ids: set[str],
    ) -> None:
        relation_key = (
            relation.source_media_id,
            relation.target_media_id,
            relation.relation_type,
        )
        if relation_key in seen_relations:
            return
        seen_relations.add(relation_key)
        if relation.target_media_id in series_ids:
            return
        grouped_relations.setdefault(relation.target_media_id, []).append(relation)

    def _rank_no_series_continuity(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        component_ids: set[str],
        internal_relations: list[AnimeRelation],
    ) -> dict[str, int]:
        ordered_ids = order_component_media_ids(
            snapshot, component_ids, internal_relations
        )
        return {media_id: index for index, media_id in enumerate(ordered_ids)}

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _resolve_best_series_anchor(
        *,
        series_line_sources: list[str],
        series_index: dict[str, int],
        promoted_anchor_media_id: str | None,
        promoted_depth: int | None,
    ) -> str | None:
        """Resolve the best anchor across direct and promoted continuity origins.

        Direct series-line origins are normalized as depth `0`.
        Promoted anchor metadata is considered alongside direct origins.
        Final tie-break rank is: earliest `series_index`, then lowest depth.
        """
        anchor_candidates: list[tuple[str, int]] = [
            (source_id, 0) for source_id in series_line_sources
        ]
        if promoted_anchor_media_id is not None and promoted_depth is not None:
            anchor_candidates.append((promoted_anchor_media_id, promoted_depth))

        if not anchor_candidates:
            return None

        return min(
            anchor_candidates,
            key=lambda candidate: (
                series_index.get(candidate[0], 999999),
                candidate[1],
            ),
        )[0]

    def _derive_promoted_target_metadata(
        self,
        *,
        promoted_relations: list[AnimeRelation],
        series_ids: set[str],
        series_index: dict[str, int],
    ) -> dict[str, dict[str, str | int]]:
        if not promoted_relations:
            return {}

        adjacency: dict[str, list[AnimeRelation]] = {}
        result: dict[str, dict[str, str | int]] = {}
        queue = deque()

        for relation in promoted_relations:
            adjacency.setdefault(relation.source_media_id, []).append(relation)
            if relation.source_media_id in series_ids:
                queue.append((relation.target_media_id, relation.source_media_id, 0))

        while queue:
            target_media_id, anchor_media_id, depth = queue.popleft()
            current = result.get(target_media_id)
            if current is not None:
                current_anchor_index = series_index.get(
                    str(current["series_anchor_media_id"]), 999999
                )
                candidate_anchor_index = series_index.get(anchor_media_id, 999999)
                current_rank = (current_anchor_index, int(current["depth"]))
                candidate_rank = (candidate_anchor_index, depth)
                if current_rank <= candidate_rank:
                    continue

            result[target_media_id] = {
                "series_anchor_media_id": anchor_media_id,
                "depth": depth,
            }
            for relation in adjacency.get(target_media_id, []):
                if relation.target_media_id in series_ids:
                    continue
                queue.append((relation.target_media_id, anchor_media_id, depth + 1))

        return result
