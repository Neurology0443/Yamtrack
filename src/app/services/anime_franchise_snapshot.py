"""Canonical MAL anime franchise snapshot service."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder

if TYPE_CHECKING:
    from app.services.anime_franchise_types import AnimeNode, AnimeRelation


ROOT_STORY_PARENT_RELATIONS = {"full_story"}
BRANCH_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting"}
)
CONTINUITY_RELATIONS = frozenset({"prequel", "sequel"})


NO_SERIES_LINE_SECONDARY_RELATIONS = {
    "side_story",
    "spin_off",
    "parent_story",
    "alternative_setting",
    "alternative_version",
    "character",
}


@dataclass(frozen=True)
class AnimeBranchRelation:
    """A branch relation oriented from main/parent component to branch component."""

    parent_media_id: str
    branch_media_id: str
    relation_type: str


@dataclass
class AnimeFranchiseSnapshot:
    """Normalized snapshot of a MAL anime franchise around a seed node."""

    root_node: AnimeNode
    nodes_by_media_id: dict[str, AnimeNode]
    all_normalized_relations: list[AnimeRelation]
    continuity_component: list[AnimeNode]
    series_line: list[AnimeNode]
    direct_anchors: list[AnimeNode]
    direct_candidates: list[AnimeRelation]
    has_series_line: bool
    fallback_anchor_media_id: str
    canonical_root_media_id: str
    promoted_continuity_candidates: list[AnimeRelation] = field(default_factory=list)
    no_series_line_secondary_candidates: list[AnimeRelation] = field(
        default_factory=list
    )
    root_story_parent_candidates: list[AnimeRelation] = field(default_factory=list)
    branch_relations: list[AnimeBranchRelation] = field(default_factory=list)


class _BranchComponents:
    """Continuity-only components used to orient branch relations."""

    def __init__(self, media_ids):
        self.parent = {str(media_id): str(media_id) for media_id in media_ids}

    def find(self, media_id):
        media_id = str(media_id)
        parent = self.parent[media_id]
        if parent != media_id:
            self.parent[media_id] = self.find(parent)
        return self.parent[media_id]

    def union(self, left_media_id, right_media_id):
        left_root = self.find(left_media_id)
        right_root = self.find(right_media_id)
        if left_root == right_root:
            return
        keep, merge = sorted((left_root, right_root), key=_media_id_key)
        self.parent[merge] = keep


class AnimeFranchiseSnapshotService:
    """Build the canonical franchise snapshot consumed by UI and import profiles."""

    def __init__(self, graph_builder: AnimeFranchiseGraphBuilder | None = None):
        """Create the service with an optional graph builder."""
        self.graph_builder = graph_builder or AnimeFranchiseGraphBuilder()

    def build(
        self,
        media_id: str,
        *,
        refresh_cache: bool = False,
    ) -> AnimeFranchiseSnapshot:
        """Build a normalized franchise snapshot for one MAL anime ID."""
        self.graph_builder.refresh_cache = refresh_cache
        root_media_id = str(media_id)
        nodes_by_media_id = dict(self.graph_builder.build(root_media_id))
        root_node = nodes_by_media_id[root_media_id]

        continuity_component = list(nodes_by_media_id.values())
        series_line = self._derive_series_line(nodes_by_media_id)
        has_series_line = bool(series_line)

        direct_anchors = self._derive_direct_anchors(series_line, root_node)
        fallback_anchor_media_id = root_node.media_id
        canonical_root_media_id = self._derive_canonical_root_media_id(
            series_line,
            continuity_component,
        )

        series_line_ids = {node.media_id for node in series_line}
        direct_candidates: list[AnimeRelation] = []
        seen_candidates: set[tuple[str, str, str]] = set()
        for anchor in direct_anchors:
            for relation in self.graph_builder.get_direct_neighbors(anchor.media_id):
                if has_series_line and relation.target_media_id in series_line_ids:
                    continue
                key = (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                if relation.target_media_id not in nodes_by_media_id:
                    target_node = self.graph_builder.ensure_node(
                        relation.target_media_id,
                    )
                    if target_node is None:
                        continue
                    nodes_by_media_id[relation.target_media_id] = target_node
                direct_candidates.append(relation)

        promoted_continuity_candidates = self._derive_promoted_continuity_candidates(
            series_line=series_line,
            nodes_by_media_id=nodes_by_media_id,
            direct_candidates=direct_candidates,
        )
        no_series_line_secondary_candidates = (
            self._derive_no_series_line_secondary_candidates(
                has_series_line=has_series_line,
                continuity_component=continuity_component,
                nodes_by_media_id=nodes_by_media_id,
            )
        )
        root_story_parent_candidates = self._derive_root_story_parent_candidates(
            root_node=root_node,
            nodes_by_media_id=nodes_by_media_id,
        )

        all_relations = [
            relation
            for node in nodes_by_media_id.values()
            for relation in node.relations
        ]
        branch_relations = self._derive_branch_relations(
            nodes_by_media_id=nodes_by_media_id,
            all_relations=all_relations,
            direct_anchors=direct_anchors,
            root_node=root_node,
        )

        return AnimeFranchiseSnapshot(
            root_node=root_node,
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=all_relations,
            continuity_component=continuity_component,
            series_line=series_line,
            direct_anchors=direct_anchors,
            direct_candidates=direct_candidates,
            promoted_continuity_candidates=promoted_continuity_candidates,
            no_series_line_secondary_candidates=no_series_line_secondary_candidates,
            root_story_parent_candidates=root_story_parent_candidates,
            has_series_line=has_series_line,
            fallback_anchor_media_id=fallback_anchor_media_id,
            canonical_root_media_id=canonical_root_media_id,
            branch_relations=branch_relations,
        )

    def _derive_branch_relations(
        self,
        *,
        nodes_by_media_id: dict[str, AnimeNode],
        all_relations: list[AnimeRelation],
        direct_anchors: list[AnimeNode],
        root_node: AnimeNode,
    ) -> list[AnimeBranchRelation]:
        """Orient branch edges from anchored parent components."""
        components = _BranchComponents(nodes_by_media_id)
        for relation in all_relations:
            if relation.relation_type not in CONTINUITY_RELATIONS:
                continue
            if (
                relation.source_media_id not in nodes_by_media_id
                or relation.target_media_id not in nodes_by_media_id
            ):
                continue
            components.union(
                relation.source_media_id,
                relation.target_media_id,
            )

        anchor_media_ids = {
            str(anchor.media_id)
            for anchor in direct_anchors
            if str(anchor.media_id) in nodes_by_media_id
        }
        anchor_components = {
            components.find(media_id)
            for media_id in anchor_media_ids
        }
        branch_root_components = self._branch_root_components(
            root_node=root_node,
            all_relations=all_relations,
            components=components,
            anchor_components=anchor_components,
        )
        parent_anchor_components = anchor_components - branch_root_components

        oriented = {}
        for relation in all_relations:
            if relation.relation_type not in BRANCH_RELATIONS:
                continue
            if (
                relation.source_media_id not in nodes_by_media_id
                or relation.target_media_id not in nodes_by_media_id
            ):
                continue

            source_component = components.find(relation.source_media_id)
            target_component = components.find(relation.target_media_id)
            if source_component == target_component:
                continue

            source_is_parent_anchor = source_component in parent_anchor_components
            target_is_parent_anchor = target_component in parent_anchor_components
            if source_is_parent_anchor == target_is_parent_anchor:
                continue

            if source_is_parent_anchor:
                parent_media_id = str(relation.source_media_id)
                branch_media_id = str(relation.target_media_id)
            else:
                parent_media_id = str(relation.target_media_id)
                branch_media_id = str(relation.source_media_id)

            branch_relation = AnimeBranchRelation(
                parent_media_id=parent_media_id,
                branch_media_id=branch_media_id,
                relation_type=relation.relation_type,
            )
            oriented[
                (
                    branch_relation.parent_media_id,
                    branch_relation.branch_media_id,
                    branch_relation.relation_type,
                )
            ] = branch_relation

        return sorted(
            oriented.values(),
            key=lambda relation: (
                _media_id_key(relation.branch_media_id),
                _media_id_key(relation.parent_media_id),
                relation.relation_type,
            ),
        )

    @staticmethod
    def _branch_root_components(
        *,
        root_node: AnimeNode,
        all_relations: list[AnimeRelation],
        components: _BranchComponents,
        anchor_components: set[str],
    ) -> set[str]:
        """Return an anchored root component directly branch-linked to an anchor."""
        root_media_id = str(root_node.media_id)
        if root_media_id not in components.parent:
            return set()

        root_component = components.find(root_media_id)
        branch_root_components = set()
        for relation in all_relations:
            if relation.relation_type not in BRANCH_RELATIONS:
                continue

            source_media_id = str(relation.source_media_id)
            target_media_id = str(relation.target_media_id)
            if root_media_id not in {source_media_id, target_media_id}:
                continue
            if (
                source_media_id not in components.parent
                or target_media_id not in components.parent
            ):
                continue

            source_component = components.find(source_media_id)
            target_component = components.find(target_media_id)
            if source_component == target_component:
                continue
            if root_component not in {source_component, target_component}:
                continue

            other_component = (
                target_component
                if source_component == root_component
                else source_component
            )
            if other_component in anchor_components:
                branch_root_components.add(root_component)

        return branch_root_components

    def _derive_root_story_parent_candidates(
        self,
        *,
        root_node: AnimeNode,
        nodes_by_media_id: dict[str, AnimeNode],
    ) -> list[AnimeRelation]:
        if root_node.media_type == "tv":
            return []

        candidates: list[AnimeRelation] = []
        seen: set[tuple[str, str, str]] = set()
        for relation in root_node.relations:
            if relation.relation_type not in ROOT_STORY_PARENT_RELATIONS:
                continue

            key = (
                relation.source_media_id,
                relation.target_media_id,
                relation.relation_type,
            )
            if key in seen:
                continue

            target_node = self.graph_builder.ensure_node(relation.target_media_id)
            if target_node is None:
                continue
            nodes_by_media_id[relation.target_media_id] = target_node
            if target_node.media_type != "tv":
                continue

            seen.add(key)
            candidates.append(relation)

        return candidates

    def _derive_no_series_line_secondary_candidates(
        self,
        *,
        has_series_line: bool,
        continuity_component: list[AnimeNode],
        nodes_by_media_id: dict[str, AnimeNode],
    ) -> list[AnimeRelation]:
        if has_series_line:
            return []

        continuity_ids = {node.media_id for node in continuity_component}
        if not continuity_ids:
            return []

        candidates: list[AnimeRelation] = []
        seen: set[tuple[str, str, str]] = set()
        for node in continuity_component:
            for relation in node.relations:
                if relation.source_media_id not in continuity_ids:
                    continue
                if relation.relation_type not in NO_SERIES_LINE_SECONDARY_RELATIONS:
                    continue

                key = (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                if key in seen:
                    continue

                if relation.target_media_id not in nodes_by_media_id:
                    target_node = self.graph_builder.ensure_node(
                        relation.target_media_id,
                    )
                    if target_node is None:
                        continue
                    nodes_by_media_id[relation.target_media_id] = target_node

                seen.add(key)
                candidates.append(relation)

        return candidates

    def _derive_promoted_continuity_candidates(  # noqa: C901
        self,
        *,
        series_line: list[AnimeNode],
        nodes_by_media_id: dict[str, AnimeNode],
        direct_candidates: list[AnimeRelation],
    ) -> list[AnimeRelation]:
        if not series_line:
            return []

        series_line_ids = {node.media_id for node in series_line}
        promoted: list[AnimeRelation] = []
        seen_relations: set[tuple[str, str, str]] = set()
        queue = deque()
        visited_nodes: set[str] = set()

        for relation in direct_candidates:
            if relation.source_media_id not in series_line_ids:
                continue
            if not self._is_non_tv_continuity_relation(
                relation,
                series_line_ids=series_line_ids,
                nodes_by_media_id=nodes_by_media_id,
            ):
                continue

            relation_key = (
                relation.source_media_id,
                relation.target_media_id,
                relation.relation_type,
            )
            if relation_key not in seen_relations:
                seen_relations.add(relation_key)
                promoted.append(relation)

            if relation.target_media_id not in visited_nodes:
                visited_nodes.add(relation.target_media_id)
                queue.append(relation.target_media_id)

        while queue:
            current_media_id = queue.popleft()
            for relation in self.graph_builder.get_direct_neighbors(current_media_id):
                if not self._is_non_tv_continuity_relation(
                    relation,
                    series_line_ids=series_line_ids,
                    nodes_by_media_id=nodes_by_media_id,
                ):
                    continue

                relation_key = (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                if relation_key not in seen_relations:
                    seen_relations.add(relation_key)
                    promoted.append(relation)

                if relation.target_media_id not in visited_nodes:
                    visited_nodes.add(relation.target_media_id)
                    queue.append(relation.target_media_id)

        return promoted

    def _is_non_tv_continuity_relation(
        self,
        relation: AnimeRelation,
        *,
        series_line_ids: set[str],
        nodes_by_media_id: dict[str, AnimeNode],
    ) -> bool:
        if relation.relation_type not in {"prequel", "sequel"}:
            return False
        if relation.target_media_id in series_line_ids:
            return False
        target_node = nodes_by_media_id.get(relation.target_media_id)
        if target_node is None:
            target_node = self.graph_builder.ensure_node(relation.target_media_id)
            if target_node is None:
                return False
            nodes_by_media_id[relation.target_media_id] = target_node
        return target_node.media_type != "tv"

    def _derive_series_line(self, graph: dict[str, AnimeNode]) -> list[AnimeNode]:
        tv_nodes = {
            node.media_id: node for node in graph.values() if node.media_type == "tv"
        }
        if not tv_nodes:
            return []

        order = self._topological_series_order(graph, tv_nodes)
        return [tv_nodes[node_id] for node_id in order if node_id in tv_nodes]

    @staticmethod
    def _derive_direct_anchors(
        series_line: list[AnimeNode],
        root_node: AnimeNode,
    ) -> list[AnimeNode]:
        if not series_line:
            return [root_node]

        series_line_ids = {node.media_id for node in series_line}
        if root_node.media_id in series_line_ids:
            return series_line

        return [*series_line, root_node]

    def _topological_series_order(
        self,
        graph: dict[str, AnimeNode],
        tv_nodes: dict[str, AnimeNode],
    ) -> list[str]:
        indegree = dict.fromkeys(tv_nodes, 0)
        adjacency = {node_id: set() for node_id in tv_nodes}

        for node in graph.values():
            for relation in node.relations:
                if relation.relation_type not in CONTINUITY_RELATIONS:
                    continue
                source_id, target_id = self._continuity_direction(
                    node.media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                if (
                    source_id in tv_nodes
                    and target_id in tv_nodes
                    and target_id not in adjacency[source_id]
                ):
                    adjacency[source_id].add(target_id)
                    indegree[target_id] += 1

        ready = sorted(
            [node_id for node_id, degree in indegree.items() if degree == 0],
            key=lambda node_id: self._date_sort_tuple(tv_nodes[node_id]),
        )
        ordered_ids = []

        while ready:
            current = ready.pop(0)
            ordered_ids.append(current)

            sorted_neighbors = sorted(
                adjacency[current],
                key=lambda node_id: self._date_sort_tuple(tv_nodes[node_id]),
            )
            for neighbor in sorted_neighbors:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
                    ready.sort(
                        key=lambda node_id: self._date_sort_tuple(tv_nodes[node_id]),
                    )

        if len(ordered_ids) != len(tv_nodes):
            remaining = [node_id for node_id in tv_nodes if node_id not in ordered_ids]
            ordered_ids.extend(
                sorted(
                    remaining,
                    key=lambda node_id: self._date_sort_tuple(tv_nodes[node_id]),
                )
            )

        return ordered_ids

    @staticmethod
    def _date_value(start_date):
        return start_date.isoformat() if start_date else "9999-12-31"

    @staticmethod
    def _date_sort_tuple(node: AnimeNode) -> tuple:
        return (
            AnimeFranchiseSnapshotService._date_value(node.start_date),
            int(node.media_id),
        )

    @staticmethod
    def _continuity_direction(
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> tuple[str, str]:
        if relation_type == "prequel":
            return target_id, source_id
        return source_id, target_id

    def _derive_canonical_root_media_id(
        self,
        series_line: list[AnimeNode],
        continuity_component: list[AnimeNode],
    ) -> str:
        if series_line:
            return series_line[0].media_id

        ordered_nodes = sorted(
            continuity_component,
            key=self._date_sort_tuple,
        )
        return ordered_nodes[0].media_id


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
