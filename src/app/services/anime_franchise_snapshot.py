"""Canonical MAL anime franchise snapshot service."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


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


class AnimeFranchiseSnapshotService:
    """Build the canonical franchise snapshot consumed by UI and import profiles."""

    def __init__(self, graph_builder: AnimeFranchiseGraphBuilder | None = None):
        self.graph_builder = graph_builder or AnimeFranchiseGraphBuilder()

    def build(
        self,
        media_id: str,
        *,
        refresh_cache: bool = False,
    ) -> AnimeFranchiseSnapshot:
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
                direct_candidates.append(relation)
                nodes_by_media_id[relation.target_media_id] = self.graph_builder.ensure_node(
                    relation.target_media_id
                )

        all_relations = [
            relation
            for node in nodes_by_media_id.values()
            for relation in node.relations
        ]

        return AnimeFranchiseSnapshot(
            root_node=root_node,
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=all_relations,
            continuity_component=continuity_component,
            series_line=series_line,
            direct_anchors=direct_anchors,
            direct_candidates=direct_candidates,
            has_series_line=has_series_line,
            fallback_anchor_media_id=fallback_anchor_media_id,
            canonical_root_media_id=canonical_root_media_id,
        )

    def _derive_series_line(self, graph: dict[str, AnimeNode]) -> list[AnimeNode]:
        tv_nodes = {
            node.media_id: node
            for node in graph.values()
            if node.media_type == "tv"
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
        return (AnimeFranchiseSnapshotService._date_value(node.start_date), int(node.media_id))

    @staticmethod
    def _continuity_direction(source_id: str, target_id: str, relation_type: str) -> tuple[str, str]:
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
