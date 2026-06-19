"""Pure resolver for grouping tracked anime into local series branches."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeNode, AnimeRelation


CONTINUITY_RELATION_TYPES = frozenset({"prequel", "sequel"})
BRANCH_RELATION_TYPES = frozenset(
    {"alternative_version", "alternative_setting", "spin_off"}
)
AFFILIATE_RELATION_TYPES = frozenset(
    {"summary", "full_story", "side_story", "parent_story"}
)
AFFILIATE_MEDIA_TYPES = frozenset({"special", "ova", "tv_special"})

BRANCH_GROUP_KINDS = {
    "alternative_version": "alternative_branch",
    "alternative_setting": "alternative_branch",
    "spin_off": "spin_off_branch",
}

BRANCH_RELATION_PRIORITY = {
    "alternative_version": 0,
    "alternative_setting": 1,
    "spin_off": 2,
}


@dataclass(frozen=True)
class LocalSeriesGroup:
    """One locally meaningful group containing tracked anime only."""

    root_media_id: str
    group_kind: str
    member_media_ids: list[str]
    context_parent_media_id: str | None = None
    context_relation_type: str | None = None


@dataclass(frozen=True)
class LocalSeriesResolution:
    """Deterministic local-series projection for one franchise snapshot."""

    groups: list[LocalSeriesGroup]
    resolver_version: str = "v1"


@dataclass(frozen=True)
class _BranchContext:
    parent_component_id: str
    parent_media_id: str
    branch_media_id: str
    relation_type: str


class _DisjointSet:
    def __init__(
        self,
        media_ids: set[str],
        *,
        primary_media_ids: set[str],
    ):
        self.parent = {media_id: media_id for media_id in media_ids}
        self.has_primary = {
            media_id: media_id in primary_media_ids for media_id in media_ids
        }

    def find(self, media_id: str) -> str:
        parent = self.parent[media_id]
        while parent != self.parent[parent]:
            parent = self.parent[parent]
        while media_id != parent:
            next_media_id = self.parent[media_id]
            self.parent[media_id] = parent
            media_id = next_media_id
        return parent

    def union(self, left_media_id: str, right_media_id: str) -> None:
        left_root = self.find(left_media_id)
        right_root = self.find(right_media_id)
        if left_root == right_root:
            return
        lower_root, higher_root = sorted((left_root, right_root), key=_media_id_key)
        self.parent[higher_root] = lower_root
        self.has_primary[lower_root] = (
            self.has_primary[left_root] or self.has_primary[right_root]
        )

    def component_has_primary(self, media_id: str) -> bool:
        return self.has_primary[self.find(media_id)]


class AnimeLocalSeriesResolver:
    """Resolve tracked anime into deterministic local continuity groups."""

    resolver_version = "v1"

    def resolve(
        self,
        snapshot: AnimeFranchiseSnapshot,
        tracked_media_ids: set[str],
    ) -> LocalSeriesResolution:
        """Return local groups without reading or mutating external state."""
        nodes = snapshot.nodes_by_media_id
        tracked_ids = {str(media_id) for media_id in tracked_media_ids}
        tracked_ids.intersection_update(nodes)
        if not tracked_ids:
            return LocalSeriesResolution(
                groups=[],
                resolver_version=self.resolver_version,
            )

        relations = self._known_relations(snapshot)
        component_by_media_id, component_members = self._build_components(
            nodes=nodes,
            relations=relations,
        )
        main_component_id = component_by_media_id.get(
            str(snapshot.canonical_root_media_id)
        )
        boundary_relations = [
            relation
            for relation in relations
            if relation.relation_type in BRANCH_RELATION_TYPES
            and component_by_media_id[relation.source_media_id]
            != component_by_media_id[relation.target_media_id]
        ]
        contexts = self._derive_branch_contexts(
            boundary_relations=boundary_relations,
            component_by_media_id=component_by_media_id,
            main_component_id=main_component_id,
        )

        sortable_groups = []
        for component_id, all_member_ids in component_members.items():
            member_ids = tracked_ids.intersection(all_member_ids)
            if not member_ids:
                continue
            group = self._build_group(
                snapshot=snapshot,
                member_ids=member_ids,
                relations=relations,
                context=contexts.get(component_id),
            )
            sortable_groups.append(
                (
                    0 if component_id == main_component_id else 1,
                    self._node_sort_key(nodes[group.root_media_id]),
                    group,
                )
            )

        groups = [
            item[2]
            for item in sorted(sortable_groups, key=lambda item: item[:2])
        ]
        return LocalSeriesResolution(
            groups=groups,
            resolver_version=self.resolver_version,
        )

    def _build_components(
        self,
        *,
        nodes: dict[str, AnimeNode],
        relations: list[AnimeRelation],
    ) -> tuple[dict[str, str], dict[str, set[str]]]:
        disjoint_set = _DisjointSet(
            set(nodes),
            primary_media_ids={
                media_id
                for media_id, node in nodes.items()
                if node.media_type not in AFFILIATE_MEDIA_TYPES
            },
        )
        branch_boundary_node_pairs = {
            frozenset(
                {
                    relation.source_media_id,
                    relation.target_media_id,
                }
            )
            for relation in relations
            if relation.relation_type in BRANCH_RELATION_TYPES
        }
        for relation in relations:
            if relation.relation_type in CONTINUITY_RELATION_TYPES:
                if self._would_merge_branch_boundary(
                    relation.source_media_id,
                    relation.target_media_id,
                    disjoint_set=disjoint_set,
                    branch_boundary_node_pairs=branch_boundary_node_pairs,
                ):
                    continue
                disjoint_set.union(
                    relation.source_media_id,
                    relation.target_media_id,
                )

        for relation in relations:
            if not self._is_affiliation_relation(relation, nodes):
                continue
            source_root = disjoint_set.find(relation.source_media_id)
            target_root = disjoint_set.find(relation.target_media_id)
            if source_root == target_root:
                continue
            if self._would_merge_branch_boundary(
                relation.source_media_id,
                relation.target_media_id,
                disjoint_set=disjoint_set,
                branch_boundary_node_pairs=branch_boundary_node_pairs,
            ):
                continue
            if (
                disjoint_set.component_has_primary(relation.source_media_id)
                and disjoint_set.component_has_primary(relation.target_media_id)
                and relation.relation_type not in AFFILIATE_RELATION_TYPES
            ):
                continue
            disjoint_set.union(
                relation.source_media_id,
                relation.target_media_id,
            )

        component_by_media_id = {
            media_id: disjoint_set.find(media_id) for media_id in nodes
        }
        component_members: dict[str, set[str]] = defaultdict(set)
        for media_id, component_id in component_by_media_id.items():
            component_members[component_id].add(media_id)
        return component_by_media_id, component_members

    @staticmethod
    def _would_merge_branch_boundary(
        left_media_id: str,
        right_media_id: str,
        *,
        disjoint_set: _DisjointSet,
        branch_boundary_node_pairs: set[frozenset[str]],
    ) -> bool:
        left_root = disjoint_set.find(left_media_id)
        right_root = disjoint_set.find(right_media_id)
        if left_root == right_root:
            return False

        merging_roots = {left_root, right_root}
        for boundary_pair in branch_boundary_node_pairs:
            boundary_left, boundary_right = tuple(boundary_pair)
            boundary_roots = {
                disjoint_set.find(boundary_left),
                disjoint_set.find(boundary_right),
            }
            if boundary_roots == merging_roots:
                return True
        return False

    def _build_group(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        member_ids: set[str],
        relations: list[AnimeRelation],
        context: _BranchContext | None,
    ) -> LocalSeriesGroup:
        root_media_id = self._select_root_media_id(
            snapshot=snapshot,
            member_ids=member_ids,
            relations=relations,
            preferred_media_id=context.branch_media_id if context else None,
        )
        return LocalSeriesGroup(
            root_media_id=root_media_id,
            group_kind=self._group_kind(
                member_count=len(member_ids),
                context=context,
            ),
            member_media_ids=self._order_member_ids(
                snapshot=snapshot,
                member_ids=member_ids,
                root_media_id=root_media_id,
            ),
            context_parent_media_id=context.parent_media_id if context else None,
            context_relation_type=context.relation_type if context else None,
        )

    @staticmethod
    def _known_relations(
        snapshot: AnimeFranchiseSnapshot,
    ) -> list[AnimeRelation]:
        nodes = snapshot.nodes_by_media_id
        unique_relations = {
            (
                str(relation.source_media_id),
                str(relation.target_media_id),
                relation.relation_type,
            ): relation
            for relation in snapshot.all_normalized_relations
            if str(relation.source_media_id) in nodes
            and str(relation.target_media_id) in nodes
        }
        return [
            unique_relations[key]
            for key in sorted(
                unique_relations,
                key=lambda item: (
                    _media_id_key(item[0]),
                    _media_id_key(item[1]),
                    item[2],
                ),
            )
        ]

    @staticmethod
    def _is_affiliation_relation(
        relation: AnimeRelation,
        nodes: dict[str, AnimeNode],
    ) -> bool:
        if relation.relation_type in AFFILIATE_RELATION_TYPES:
            return True
        return bool(
            {
                nodes[relation.source_media_id].media_type,
                nodes[relation.target_media_id].media_type,
            }
            & AFFILIATE_MEDIA_TYPES
        )

    def _derive_branch_contexts(
        self,
        *,
        boundary_relations: list[AnimeRelation],
        component_by_media_id: dict[str, str],
        main_component_id: str | None,
    ) -> dict[str, _BranchContext]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for relation in boundary_relations:
            source_component = component_by_media_id[relation.source_media_id]
            target_component = component_by_media_id[relation.target_media_id]
            adjacency[source_component].add(target_component)
            adjacency[target_component].add(source_component)

        distances: dict[str, int] = {}
        if main_component_id is not None:
            distances[main_component_id] = 0
            queue = deque([main_component_id])
            while queue:
                component_id = queue.popleft()
                for neighbor_id in sorted(
                    adjacency[component_id],
                    key=_media_id_key,
                ):
                    if neighbor_id in distances:
                        continue
                    distances[neighbor_id] = distances[component_id] + 1
                    queue.append(neighbor_id)

        candidates: dict[str, list[_BranchContext]] = defaultdict(list)
        for relation in boundary_relations:
            source_component = component_by_media_id[relation.source_media_id]
            target_component = component_by_media_id[relation.target_media_id]
            source_distance = distances.get(source_component)
            target_distance = distances.get(target_component)

            if source_distance is not None and (
                target_distance is None or source_distance < target_distance
            ):
                child_component = target_component
                context = _BranchContext(
                    parent_component_id=source_component,
                    parent_media_id=relation.source_media_id,
                    branch_media_id=relation.target_media_id,
                    relation_type=relation.relation_type,
                )
            elif target_distance is not None and (
                source_distance is None or target_distance < source_distance
            ):
                child_component = source_component
                context = _BranchContext(
                    parent_component_id=target_component,
                    parent_media_id=relation.target_media_id,
                    branch_media_id=relation.source_media_id,
                    relation_type=relation.relation_type,
                )
            else:
                continue

            candidates[child_component].append(context)

        return {
            component_id: min(
                component_candidates,
                key=lambda context: (
                    distances.get(context.parent_component_id, 10**9),
                    BRANCH_RELATION_PRIORITY[context.relation_type],
                    _media_id_key(context.parent_media_id),
                    _media_id_key(context.branch_media_id),
                ),
            )
            for component_id, component_candidates in candidates.items()
        }

    def _select_root_media_id(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        member_ids: set[str],
        relations: list[AnimeRelation],
        preferred_media_id: str | None,
    ) -> str:
        incoming_from_tracked = defaultdict(set)
        outgoing_to_tracked = defaultdict(set)
        for relation in relations:
            if relation.relation_type not in CONTINUITY_RELATION_TYPES:
                continue
            earlier_id, later_id = self._continuity_direction(relation)
            if earlier_id not in member_ids or later_id not in member_ids:
                continue
            incoming_from_tracked[later_id].add(earlier_id)
            outgoing_to_tracked[earlier_id].add(later_id)

        local_parent_ids = {
            media_id
            for media_id in member_ids
            if outgoing_to_tracked[media_id] and not incoming_from_tracked[media_id]
        }
        if local_parent_ids:
            candidates = local_parent_ids
        elif preferred_media_id in member_ids:
            candidates = {preferred_media_id}
        else:
            candidates = member_ids
        continuity_order = self._continuity_order(snapshot)
        return min(
            candidates,
            key=lambda media_id: (
                continuity_order.get(media_id, 10**9),
                self._node_sort_key(snapshot.nodes_by_media_id[media_id]),
            ),
        )

    def _order_member_ids(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        member_ids: set[str],
        root_media_id: str,
    ) -> list[str]:
        continuity_order = self._continuity_order(snapshot)
        remaining_ids = member_ids - {root_media_id}
        return [
            root_media_id,
            *sorted(
                remaining_ids,
                key=lambda media_id: (
                    continuity_order.get(media_id, 10**9),
                    self._node_sort_key(snapshot.nodes_by_media_id[media_id]),
                ),
            ),
        ]

    @staticmethod
    def _continuity_order(
        snapshot: AnimeFranchiseSnapshot,
    ) -> dict[str, int]:
        ordered_ids = []
        seen_ids = set()
        for node in [*snapshot.series_line, *snapshot.continuity_component]:
            if node.media_id in seen_ids:
                continue
            seen_ids.add(node.media_id)
            ordered_ids.append(node.media_id)
        return {
            media_id: index for index, media_id in enumerate(ordered_ids)
        }

    @staticmethod
    def _continuity_direction(relation: AnimeRelation) -> tuple[str, str]:
        if relation.relation_type == "prequel":
            return relation.target_media_id, relation.source_media_id
        return relation.source_media_id, relation.target_media_id

    @staticmethod
    def _group_kind(
        *,
        member_count: int,
        context: _BranchContext | None,
    ) -> str:
        if context is not None:
            return BRANCH_GROUP_KINDS[context.relation_type]
        if member_count == 1:
            return "singleton"
        return "main_continuity"

    @staticmethod
    def _node_sort_key(node: AnimeNode) -> tuple[str, tuple[int, int | str]]:
        return (
            node.start_date.isoformat() if node.start_date else "9999-12-31",
            _media_id_key(node.media_id),
        )


def _media_id_key(media_id: str) -> tuple[int, int | str]:
    media_id = str(media_id)
    if media_id.isdigit():
        return (0, int(media_id))
    return (1, media_id)
