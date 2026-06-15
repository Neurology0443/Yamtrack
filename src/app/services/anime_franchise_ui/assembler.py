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
from datetime import date
from typing import TYPE_CHECKING

from .candidates import UiCandidate

NO_SERIES_LINE_CONTINUITY_RELATIONS = {"prequel", "sequel"}
if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeRelation


class UiCandidateAssembler:
    """Build canonical secondary candidates while keeping Series separate."""

    def build(self, snapshot: AnimeFranchiseSnapshot) -> list[UiCandidate]:  # noqa: C901, PLR0915
        """Build secondary candidates and preserve representative relations."""
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
        root_story_parent_relations = (
            getattr(snapshot, "root_story_parent_candidates", []) or []
        )
        root_story_parent_keys = {
            (relation.source_media_id, relation.target_media_id, relation.relation_type)
            for relation in root_story_parent_relations
        }

        candidate_relations = [
            *snapshot.direct_candidates,
            *promoted_relations,
            *root_story_parent_relations,
        ]
        no_series_line_continuity_keys: set[tuple[str, str, str]] = set()
        no_series_line_secondary_keys: set[tuple[str, str, str]] = set()
        no_series_line_order = self._derive_no_series_line_continuity_order(snapshot)
        if not snapshot.has_series_line:
            no_series_continuity_relations = (
                self._derive_no_series_line_continuity_relations(snapshot)
            )
            no_series_secondary_relations = (
                getattr(snapshot, "no_series_line_secondary_candidates", []) or []
            )
            no_series_line_continuity_keys = {
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                for relation in no_series_continuity_relations
            }
            no_series_line_secondary_keys = {
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                for relation in no_series_secondary_relations
            }
            candidate_relations.extend(no_series_continuity_relations)
            candidate_relations.extend(no_series_secondary_relations)

        grouped_relations: dict[str, list[AnimeRelation]] = {}
        seen_relations: set[tuple[str, str, str]] = set()
        for relation in candidate_relations:
            relation_key = (
                relation.source_media_id,
                relation.target_media_id,
                relation.relation_type,
            )
            if relation_key in seen_relations:
                continue
            seen_relations.add(relation_key)
            if relation.target_media_id in series_ids:
                continue
            grouped_relations.setdefault(relation.target_media_id, []).append(relation)

        candidates: list[UiCandidate] = []
        for target_media_id, relations in grouped_relations.items():
            node = snapshot.nodes_by_media_id.get(target_media_id)
            if node is None:
                continue

            relation_types = self._ordered_unique(
                [relation.relation_type for relation in relations],
            )
            source_media_ids = self._ordered_unique(
                [relation.source_media_id for relation in relations],
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
            representative_relation = self._resolve_representative_relation(
                relations=relations,
                series_ids=series_ids,
            )
            representative_relation_type = (
                representative_relation.relation_type
                if representative_relation is not None
                else "unknown"
            )
            relation_source_media_id = (
                representative_relation.source_media_id
                if representative_relation is not None
                else linked_series_line_media_id
            )
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
            is_no_series_line_continuity = any(
                (
                    (
                        relation.source_media_id,
                        relation.target_media_id,
                        relation.relation_type,
                    )
                    in no_series_line_continuity_keys
                    or (
                        not snapshot.has_series_line
                        and relation.relation_type
                        in NO_SERIES_LINE_CONTINUITY_RELATIONS
                        and relation.source_media_id in no_series_line_order
                        and relation.target_media_id in no_series_line_order
                    )
                )
                for relation in relations
            )
            is_no_series_line_secondary = any(
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                in no_series_line_secondary_keys
                for relation in relations
            )
            is_root_story_parent = any(
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                in root_story_parent_keys
                for relation in relations
            )
            metadata = {
                "is_promoted_continuity": is_promoted_continuity,
                "promoted_from_series_line_media_id": promoted_metadata.get(
                    "series_anchor_media_id",
                ),
                "promoted_depth": promoted_metadata.get("depth"),
                "origins": [
                    {
                        "source_media_id": relation.source_media_id,
                        "relation_type": relation.relation_type,
                        "is_from_series_line": (relation.source_media_id in series_ids),
                        "is_from_root_node": (
                            relation.source_media_id == root_media_id
                        ),
                    }
                    for relation in relations
                ],
            }
            if is_no_series_line_continuity and not is_root_story_parent:
                metadata["section_sort_rank"] = no_series_line_order.get(node.media_id)
            if is_no_series_line_secondary:
                metadata["is_no_series_line_secondary"] = True
            if is_root_story_parent:
                metadata["is_root_story_parent"] = True

            candidates.append(
                UiCandidate(
                    media_id=node.media_id,
                    title=node.title,
                    image=node.image,
                    source=node.source,
                    media_type=node.media_type,
                    relation_type=representative_relation_type,
                    start_date=node.start_date,
                    runtime_minutes=node.runtime_minutes,
                    episode_count=node.episode_count,
                    linked_series_line_media_id=linked_series_line_media_id,
                    linked_series_line_index=(
                        series_index.get(linked_series_line_media_id, 0)
                        if linked_series_line_media_id is not None
                        else None
                    ),
                    relation_source_media_id=relation_source_media_id,
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

    @staticmethod
    def _derive_no_series_line_continuity_order(  # noqa: C901, PLR0912
        snapshot: AnimeFranchiseSnapshot,
    ) -> dict[str, int]:
        if snapshot.has_series_line:
            return {}

        continuity_ids = {node.media_id for node in snapshot.continuity_component}
        if not continuity_ids:
            return {}

        node_dates = {
            node.media_id: node.start_date for node in snapshot.continuity_component
        }

        def sort_key(media_id: str) -> tuple[date, int]:
            return (node_dates.get(media_id) or date.max, int(media_id))

        outgoing: dict[str, set[str]] = {media_id: set() for media_id in continuity_ids}
        indegree: dict[str, int] = dict.fromkeys(continuity_ids, 0)
        for relation in snapshot.all_normalized_relations:
            if relation.relation_type not in NO_SERIES_LINE_CONTINUITY_RELATIONS:
                continue
            if relation.source_media_id not in continuity_ids:
                continue
            if relation.target_media_id not in continuity_ids:
                continue

            if relation.relation_type == "prequel":
                before_id, after_id = relation.target_media_id, relation.source_media_id
            else:
                before_id, after_id = relation.source_media_id, relation.target_media_id

            if after_id in outgoing[before_id]:
                continue
            outgoing[before_id].add(after_id)
            indegree[after_id] += 1

        ready = deque(
            sorted(
                (media_id for media_id, degree in indegree.items() if degree == 0),
                key=sort_key,
            )
        )
        ordered: list[str] = []
        while ready:
            media_id = ready.popleft()
            ordered.append(media_id)
            newly_ready: list[str] = []
            for target_id in sorted(outgoing[media_id], key=sort_key):
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    newly_ready.append(target_id)
            for target_id in sorted(newly_ready, key=sort_key):
                ready.append(target_id)
            ready = deque(sorted(ready, key=sort_key))

        remaining = sorted(continuity_ids - set(ordered), key=sort_key)
        return {
            media_id: index for index, media_id in enumerate([*ordered, *remaining])
        }

    @staticmethod
    def _derive_no_series_line_continuity_relations(
        snapshot: AnimeFranchiseSnapshot,
    ) -> list[AnimeRelation]:
        if snapshot.has_series_line:
            return []

        continuity_ids = {node.media_id for node in snapshot.continuity_component}
        if len(continuity_ids) <= 1:
            return []

        relations: list[AnimeRelation] = []
        seen: set[tuple[str, str, str]] = set()

        for relation in snapshot.all_normalized_relations:
            if relation.relation_type not in NO_SERIES_LINE_CONTINUITY_RELATIONS:
                continue
            if relation.source_media_id not in continuity_ids:
                continue
            if relation.target_media_id not in continuity_ids:
                continue

            key = (
                relation.source_media_id,
                relation.target_media_id,
                relation.relation_type,
            )
            if key in seen:
                continue
            seen.add(key)
            relations.append(relation)

        return relations

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _resolve_representative_relation(
        *,
        relations: list[AnimeRelation],
        series_ids: set[str],
    ) -> AnimeRelation | None:
        """Resolve the relation that drives both badge type and tooltip source."""
        series_relations = [
            relation for relation in relations if relation.source_media_id in series_ids
        ]
        if series_relations:
            return series_relations[0]

        return relations[0] if relations else None

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
                    str(current["series_anchor_media_id"]),
                    999999,
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
