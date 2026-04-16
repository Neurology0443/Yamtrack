"""Service-first MAL anime grouping engine for franchise sections."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_rules import get_section_rules
from app.services.anime_franchise_types import (
    AnimeFranchiseCandidate,
    AnimeFranchiseSectionRule,
    AnimeFranchiseSectionView,
    AnimeFranchiseViewModel,
    AnimeNode,
)

if TYPE_CHECKING:
    from datetime import date


class AnimeFranchiseService:
    """Build the MAL anime franchise view model used by the details UI."""

    SERIES_LINE_KEY = "series_line"

    def __init__(self, graph_builder: AnimeFranchiseGraphBuilder | None = None):
        """Create the service with an optional graph builder."""
        self.graph_builder = graph_builder or AnimeFranchiseGraphBuilder()

    def build(self, media_id: str) -> AnimeFranchiseViewModel:
        """Build the full franchise payload from a MAL anime seed id."""
        graph = self.graph_builder.build(str(media_id))
        root_node = graph[str(media_id)]

        series_line_nodes = self._derive_series_line(graph)
        series_line_ids = {node.media_id for node in series_line_nodes}

        candidate_map = self._build_candidates(
            series_line_nodes,
            series_line_ids,
            root_node,
        )
        grouped_sections = self._classify_candidates(list(candidate_map.values()))

        ordered_sections = []
        for rule in get_section_rules():
            if rule.key == "ignored":
                continue

            section_entries = [
                self._node_to_entry(
                    candidate_map[item.media_id],
                    graph[item.media_id],
                )
                for item in grouped_sections[rule.key]
            ]
            ordered_sections.append(
                AnimeFranchiseSectionView(
                    key=rule.key,
                    title=rule.title,
                    entries=section_entries,
                    visible_in_ui=rule.visible_in_ui,
                    hidden_if_empty=rule.hidden_if_empty,
                )
            )

        series_entries = [
            self._node_to_entry_from_node(
                node,
                is_current=node.media_id == str(media_id),
            )
            for node in series_line_nodes
        ]

        return AnimeFranchiseViewModel(
            root_media_id=str(media_id),
            display_title=root_node.title,
            series_line_entries=series_entries,
            sections=ordered_sections,
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

    def _build_candidates(
        self,
        series_line_nodes: list[AnimeNode],
        series_line_ids: set[str],
        root_node: AnimeNode,
    ) -> dict[str, AnimeFranchiseCandidate]:
        candidates: dict[str, AnimeFranchiseCandidate] = {}
        line_index_map = {
            node.media_id: idx
            for idx, node in enumerate(series_line_nodes)
        }

        has_series_line = bool(series_line_nodes)
        direct_anchor_nodes = series_line_nodes or [root_node]
        for anchor in direct_anchor_nodes:
            for relation in self.graph_builder.get_direct_neighbors(anchor.media_id):
                target_id = relation.target_media_id
                if target_id in series_line_ids:
                    continue

                target_node = self.graph_builder.ensure_node(target_id)
                candidate = AnimeFranchiseCandidate(
                    media_id=target_node.media_id,
                    title=target_node.title,
                    image=target_node.image,
                    source=target_node.source,
                    media_type=target_node.media_type,
                    start_date=target_node.start_date,
                    relation_type=relation.relation_type,
                    is_current=target_node.media_id == root_node.media_id,
                    is_direct_from_series_line=True,
                    linked_series_line_media_id=(
                        anchor.media_id if has_series_line else root_node.media_id
                    ),
                    linked_series_line_index=(
                        line_index_map.get(anchor.media_id) if has_series_line else 0
                    ),
                )
                existing = candidates.get(candidate.media_id)
                if existing is None:
                    candidates[candidate.media_id] = candidate
                    continue

                if self._candidate_sort_key(
                    candidate,
                    "continuity_extras",
                ) < self._candidate_sort_key(existing, "continuity_extras"):
                    candidates[candidate.media_id] = candidate

        return candidates

    def _classify_candidates(
        self,
        candidates: list[AnimeFranchiseCandidate],
    ) -> dict[str, list[AnimeFranchiseCandidate]]:
        sections: dict[str, list[AnimeFranchiseCandidate]] = defaultdict(list)
        rules = get_section_rules()

        for candidate in candidates:
            for rule in rules:
                if self._matches_rule(candidate, rule):
                    sections[rule.key].append(candidate)
                    break

        rules_by_key = {rule.key: rule for rule in rules}
        for section_key, section_candidates in sections.items():
            primary_rule = rules_by_key[section_key]
            section_candidates.sort(
                key=lambda candidate: self._candidate_sort_key(
                    candidate,
                    primary_rule.sort_mode,
                )
            )

        return sections

    def _matches_rule(  # noqa: PLR0911
        self,
        candidate: AnimeFranchiseCandidate,
        rule: AnimeFranchiseSectionRule,
    ) -> bool:
        if rule.predicate and not rule.predicate(candidate):
            return False

        if (
            rule.include_relation_types
            and candidate.relation_type not in rule.include_relation_types
        ):
            return False
        if candidate.relation_type in rule.exclude_relation_types:
            return False

        if (
            rule.include_media_types
            and candidate.media_type not in rule.include_media_types
        ):
            return False
        if candidate.media_type in rule.exclude_media_types:
            return False

        if (
            rule.direct_from_series_line_only
            and not candidate.is_direct_from_series_line
        ):
            return False

        return not (
            not rule.allow_indirect_candidates
            and not candidate.is_direct_from_series_line
        )

    def _node_to_entry(
        self,
        candidate: AnimeFranchiseCandidate,
        node: AnimeNode,
    ) -> dict:
        entry = self._node_to_entry_from_node(node, is_current=candidate.is_current)
        entry.update(
            {
                "relation_type": candidate.relation_type,
                "linked_series_line_media_id": candidate.linked_series_line_media_id,
                "linked_series_line_index": candidate.linked_series_line_index,
            }
        )
        return entry

    @staticmethod
    def _node_to_entry_from_node(node: AnimeNode, *, is_current: bool) -> dict:
        return {
            "media_id": node.media_id,
            "title": node.title,
            "image": node.image,
            "source": node.source,
            "media_type": "anime",
            "anime_media_type": node.media_type,
            "relation_type": None,
            "linked_series_line_media_id": None,
            "linked_series_line_index": None,
            "is_current": is_current,
        }

    def _candidate_sort_key(
        self,
        candidate: AnimeFranchiseCandidate,
        sort_mode: str,
    ) -> tuple:
        linked_index = (
            candidate.linked_series_line_index
            if candidate.linked_series_line_index is not None
            else 10_000
        )
        base_key = (
            linked_index,
            self._date_value(candidate.start_date),
            int(candidate.media_id),
        )

        if sort_mode == "continuity_extras":
            relation_rank = 0 if candidate.relation_type == "prequel" else 1
            return (
                linked_index,
                relation_rank,
                self._date_value(candidate.start_date),
                int(candidate.media_id),
            )

        return base_key

    @staticmethod
    def _date_value(start_date: date | None) -> str:
        return start_date.isoformat() if start_date else "9999-12-31"

    @staticmethod
    def _date_sort_tuple(node: AnimeNode) -> tuple:
        return (
            AnimeFranchiseService._date_value(node.start_date),
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
