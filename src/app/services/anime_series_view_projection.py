"""Pure Anime Series View projection built from canonical franchise snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot

from app.services.anime_relation_rules import (
    BRANCH_BOUNDARY_RELATIONS,
    CONTINUITY_RELATIONS,
    GROUPABLE_RELATIONS,
)


@dataclass(frozen=True)
class AnimeSeriesViewDisplay:
    """Snapshot metadata required to render a Series View card."""

    media_id: str
    title: str
    image: str
    media_type: str
    start_date: date | None


@dataclass(frozen=True)
class AnimeSeriesViewProjection:
    """Persistable result of one Series View projection."""

    groups: tuple[AnimeSeriesViewGroup, ...]
    projection_version: str


@dataclass(frozen=True)
class AnimeSeriesViewGroup:
    """One stable logical card in Anime Series View."""

    root_media_id: str
    display_media_id: str
    display: AnimeSeriesViewDisplay
    group_kind: str
    member_media_ids: tuple[str, ...]
    context_parent_media_id: str | None = None
    context_parent_title: str | None = None
    context_relation_type: str | None = None


class _DisjointSet:
    def __init__(self, media_ids):
        self.parent = {media_id: media_id for media_id in media_ids}
        self.members = {media_id: {media_id} for media_id in media_ids}

    def find(self, media_id):
        parent = self.parent[media_id]
        if parent != media_id:
            self.parent[media_id] = self.find(parent)
        return self.parent[media_id]

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return left_root
        if _media_id_key(right_root) < _media_id_key(left_root):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        self.members[left_root].update(self.members.pop(right_root))
        return left_root


class AnimeSeriesViewProjectionBuilder:
    """Split a canonical snapshot into deterministic local Series View cards."""

    projection_version = "v2"

    def build(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        tracked_media_ids: Iterable[str],
    ) -> AnimeSeriesViewProjection:
        """Project tracked entries found inside a canonical snapshot."""
        nodes = snapshot.nodes_by_media_id
        tracked_ids = {
            str(media_id)
            for media_id in tracked_media_ids
            if str(media_id) in nodes
        }
        if not tracked_ids:
            return AnimeSeriesViewProjection(
                groups=(),
                projection_version=self.projection_version,
            )

        relations = self._normalized_relations(snapshot)
        branch_boundaries = {
            frozenset((relation.source_media_id, relation.target_media_id))
            for relation in relations
            if relation.relation_type in BRANCH_BOUNDARY_RELATIONS
            and relation.source_media_id != relation.target_media_id
        }
        components = self._series_view_components(
            nodes=nodes,
            relations=relations,
            branch_boundaries=branch_boundaries,
        )
        component_members = {
            root: frozenset(members)
            for root, members in components.members.items()
        }
        branch_contexts = self._project_branch_contexts(
            snapshot=snapshot,
            relations=relations,
            components=components,
            component_members=component_members,
            nodes=nodes,
        )
        series_line_ids = {
            str(node.media_id) for node in snapshot.series_line
        }

        groups = []
        for component_id, component_media_ids in component_members.items():
            member_ids = tracked_ids & component_media_ids
            if not member_ids:
                continue
            representative = self._representative_node(
                component_media_ids=component_media_ids,
                snapshot=snapshot,
                nodes=nodes,
            )
            context = branch_contexts.get(component_id)
            groups.append(
                AnimeSeriesViewGroup(
                    root_media_id=representative.media_id,
                    display_media_id=representative.media_id,
                    display=self._display(representative),
                    group_kind=self._group_kind(
                        component_media_ids=component_media_ids,
                        representative_media_id=representative.media_id,
                        series_line_ids=series_line_ids,
                        context=context,
                    ),
                    member_media_ids=self._order_members(
                        member_ids=member_ids,
                        snapshot=snapshot,
                        relations=relations,
                        nodes=nodes,
                    ),
                    context_parent_media_id=context[0] if context else None,
                    context_parent_title=context[1] if context else None,
                    context_relation_type=context[2] if context else None,
                )
            )

        groups.sort(
            key=lambda group: self._representative_sort_key(
                media_id=group.root_media_id,
                snapshot=snapshot,
                nodes=nodes,
            )
        )
        return AnimeSeriesViewProjection(
            groups=tuple(groups),
            projection_version=self.projection_version,
        )

    @staticmethod
    def _normalized_relations(snapshot):
        nodes = snapshot.nodes_by_media_id
        unique = {
            (
                str(relation.source_media_id),
                str(relation.target_media_id),
                str(relation.relation_type),
            ): relation
            for relation in snapshot.all_normalized_relations
            if str(relation.source_media_id) in nodes
            and str(relation.target_media_id) in nodes
        }
        return tuple(
            unique[key]
            for key in sorted(
                unique,
                key=lambda value: (
                    _media_id_key(value[0]),
                    _media_id_key(value[1]),
                    value[2],
                ),
            )
        )

    @staticmethod
    def _series_view_components(*, nodes, relations, branch_boundaries):
        components = _DisjointSet(nodes)
        for relation in relations:
            if relation.relation_type not in GROUPABLE_RELATIONS:
                continue
            left = relation.source_media_id
            right = relation.target_media_id
            if frozenset((left, right)) in branch_boundaries:
                continue
            left_root = components.find(left)
            right_root = components.find(right)
            if left_root == right_root:
                continue
            merged_members = (
                components.members[left_root] | components.members[right_root]
            )
            if any(boundary <= merged_members for boundary in branch_boundaries):
                continue
            components.union(left, right)
        return components

    def _project_branch_contexts(
        self,
        *,
        snapshot,
        relations,
        components,
        component_members,
        nodes,
    ):
        contexts = {}
        ambiguous = set()
        for relation in relations:
            if relation.relation_type not in BRANCH_BOUNDARY_RELATIONS:
                continue
            left_component = components.find(relation.source_media_id)
            right_component = components.find(relation.target_media_id)
            if left_component == right_component:
                continue
            orientation = self._visual_parent_components(
                left_component=left_component,
                right_component=right_component,
                component_members=component_members,
                snapshot=snapshot,
            )
            if orientation is None:
                continue
            parent_component, branch_component = orientation
            parent = self._representative_node(
                component_media_ids=component_members[parent_component],
                snapshot=snapshot,
                nodes=nodes,
            )
            candidate = (
                parent.media_id,
                parent.title,
                relation.relation_type,
            )
            previous = contexts.get(branch_component)
            if previous is not None and previous != candidate:
                ambiguous.add(branch_component)
            else:
                contexts[branch_component] = candidate
        return {
            component_id: context
            for component_id, context in contexts.items()
            if component_id not in ambiguous
        }

    @staticmethod
    def _visual_parent_components(
        *,
        left_component,
        right_component,
        component_members,
        snapshot,
    ):
        left_members = component_members[left_component]
        right_members = component_members[right_component]
        series_line_ids = {
            str(node.media_id) for node in snapshot.series_line
        }
        anchors = (
            series_line_ids,
            {str(snapshot.canonical_root_media_id)},
            {str(snapshot.root_node.media_id)},
        )
        for anchor_ids in anchors:
            left_has_anchor = bool(left_members & anchor_ids)
            right_has_anchor = bool(right_members & anchor_ids)
            if left_has_anchor == right_has_anchor:
                continue
            if left_has_anchor:
                return left_component, right_component
            return right_component, left_component
        return None

    @staticmethod
    def _representative_node(*, component_media_ids, snapshot, nodes):
        for series_node in snapshot.series_line:
            media_id = str(series_node.media_id)
            if media_id in component_media_ids:
                return nodes[media_id]
        tv_nodes = [
            nodes[media_id]
            for media_id in component_media_ids
            if nodes[media_id].media_type.lower() in {"tv", "ona"}
        ]
        if tv_nodes:
            return min(tv_nodes, key=_node_key)
        return min(
            (nodes[media_id] for media_id in component_media_ids),
            key=_node_key,
        )

    @staticmethod
    def _display(node):
        return AnimeSeriesViewDisplay(
            media_id=str(node.media_id),
            title=str(node.title),
            image=str(node.image),
            media_type=str(node.media_type),
            start_date=node.start_date,
        )

    @staticmethod
    def _group_kind(
        *,
        component_media_ids,
        representative_media_id,
        series_line_ids,
        context,
    ):
        if context and context[2] == "spin_off":
            return "spin_off"
        if context and context[2] in {"alternative_version", "alternative_setting"}:
            return "alternative_branch"
        if (
            len(component_media_ids) > 1
            or representative_media_id in series_line_ids
        ):
            return "main_continuity"
        return "singleton"

    def _order_members(self, *, member_ids, snapshot, relations, nodes):
        series_order = {
            str(node.media_id): index
            for index, node in enumerate(snapshot.series_line)
        }
        series_members = sorted(
            (media_id for media_id in member_ids if media_id in series_order),
            key=series_order.__getitem__,
        )
        remaining = set(member_ids) - set(series_members)
        continuity_order = self._continuity_order(
            member_ids=remaining,
            relations=relations,
            nodes=nodes,
        )
        return (*series_members, *continuity_order)

    @staticmethod
    def _continuity_order(*, member_ids, relations, nodes):
        predecessors = {media_id: set() for media_id in member_ids}
        successors = {media_id: set() for media_id in member_ids}
        for relation in relations:
            if (
                relation.relation_type not in CONTINUITY_RELATIONS
                or relation.source_media_id not in member_ids
                or relation.target_media_id not in member_ids
            ):
                continue
            if relation.relation_type == "sequel":
                before, after = relation.source_media_id, relation.target_media_id
            else:
                before, after = relation.target_media_id, relation.source_media_id
            predecessors[after].add(before)
            successors[before].add(after)

        ready = sorted(
            (media_id for media_id in member_ids if not predecessors[media_id]),
            key=lambda media_id: _node_key(nodes[media_id]),
        )
        ordered = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for successor in sorted(successors[current], key=_media_id_key):
                predecessors[successor].discard(current)
                if not predecessors[successor] and successor not in ordered:
                    ready.append(successor)
                    ready.sort(key=lambda media_id: _node_key(nodes[media_id]))
        return (
            *ordered,
            *sorted(
                member_ids - set(ordered),
                key=lambda media_id: _node_key(nodes[media_id]),
            ),
        )

    @staticmethod
    def _representative_sort_key(*, media_id, snapshot, nodes):
        series_order = {
            str(node.media_id): index
            for index, node in enumerate(snapshot.series_line)
        }
        if media_id in series_order:
            return (0, series_order[media_id], _media_id_key(media_id))
        return (1, *_node_key(nodes[media_id]))


def _node_key(node):
    return (
        node.start_date is None,
        node.start_date,
        _media_id_key(node.media_id),
    )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
