"""Pure Anime Series View projection built from canonical franchise snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeRelation


CONTINUITY_RELATIONS = frozenset({"prequel", "sequel"})
BRANCH_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting"},
)
AFFILIATE_RELATIONS = frozenset(
    {"side_story", "parent_story", "summary", "full_story"},
)
STRONG_AFFILIATE_RELATIONS = frozenset({"parent_story", "full_story"})


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
    group_kind: str
    member_media_ids: tuple[str, ...]
    context_parent_media_id: str | None = None
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
    """Build deterministic local groups without DB or provider access."""

    projection_version = "v1"

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
            if relation.relation_type in BRANCH_RELATIONS
            and relation.source_media_id != relation.target_media_id
        }
        components = self._continuity_components(
            nodes=nodes,
            relations=relations,
            branch_boundaries=branch_boundaries,
        )
        tracked_by_component = self._tracked_by_component(components, tracked_ids)
        affiliate_parents, affiliate_contexts = self._project_affiliate_contexts(
            relations=relations,
            components=components,
            tracked_by_component=tracked_by_component,
            branch_boundaries=branch_boundaries,
        )
        branch_contexts = self._project_branch_contexts(
            relations=relations,
            components=components,
            tracked_by_component=tracked_by_component,
        )

        grouped_components = defaultdict(set)
        for component_id, member_ids in tracked_by_component.items():
            if not member_ids:
                continue
            grouped_components[
                self._collapsed_component(component_id, affiliate_parents)
            ].add(component_id)

        groups = []
        for group_component, included_components in grouped_components.items():
            member_ids = {
                media_id
                for component_id in included_components
                for media_id in tracked_by_component[component_id]
            }
            primary_members = tracked_by_component[group_component]
            ordered_primary_members = self._order_members(
                member_ids=primary_members,
                relations=relations,
                nodes=nodes,
            )
            ordered_all_members = self._order_members(
                member_ids=member_ids,
                relations=relations,
                nodes=nodes,
            )
            ordered_members = (
                *ordered_primary_members,
                *(
                    media_id
                    for media_id in ordered_all_members
                    if media_id not in primary_members
                ),
            )
            root_media_id = ordered_members[0]
            context = self._group_context(
                included_components=included_components,
                branch_contexts=branch_contexts,
                affiliate_contexts=affiliate_contexts,
            )
            group_kind = self._group_kind(
                member_ids=member_ids,
                included_components=included_components,
                context=context,
            )
            groups.append(
                AnimeSeriesViewGroup(
                    root_media_id=root_media_id,
                    display_media_id=self._display_media_id(
                        ordered_members=ordered_members,
                        nodes=nodes,
                    ),
                    group_kind=group_kind,
                    member_media_ids=ordered_members,
                    context_parent_media_id=context[0] if context else None,
                    context_relation_type=context[1] if context else None,
                )
            )

        groups.sort(key=lambda group: _node_key(nodes[group.root_media_id]))
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

    def _continuity_components(self, *, nodes, relations, branch_boundaries):
        components = _DisjointSet(nodes)
        for relation in relations:
            if relation.relation_type not in CONTINUITY_RELATIONS:
                continue
            left = relation.source_media_id
            right = relation.target_media_id
            left_root = components.find(left)
            right_root = components.find(right)
            if left_root == right_root:
                continue
            merged = components.members[left_root] | components.members[right_root]
            if any(boundary <= merged for boundary in branch_boundaries):
                continue
            components.union(left, right)
        return components

    @staticmethod
    def _tracked_by_component(components, tracked_ids):
        tracked_by_component = defaultdict(set)
        for media_id in tracked_ids:
            tracked_by_component[components.find(media_id)].add(media_id)
        return tracked_by_component

    def _project_branch_contexts(
        self,
        *,
        relations,
        components,
        tracked_by_component,
    ):
        contexts = {}
        ambiguous = set()
        observed = set()
        for relation in relations:
            if relation.relation_type not in BRANCH_RELATIONS:
                continue
            source_component = components.find(relation.source_media_id)
            target_component = components.find(relation.target_media_id)
            if source_component == target_component:
                continue
            reverse_key = (
                relation.target_media_id,
                relation.source_media_id,
                relation.relation_type,
            )
            if reverse_key in observed:
                ambiguous.update((source_component, target_component))
            observed.add(
                (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
            )
            if not tracked_by_component.get(target_component):
                continue
            parent_id = min(
                tracked_by_component.get(source_component)
                or {relation.source_media_id},
                key=_media_id_key,
            )
            candidate = (parent_id, relation.relation_type)
            previous = contexts.get(target_component)
            if previous is not None and previous != candidate:
                ambiguous.add(target_component)
            else:
                contexts[target_component] = candidate
        return {
            component_id: context
            for component_id, context in contexts.items()
            if component_id not in ambiguous
        }

    def _project_affiliate_contexts(
        self,
        *,
        relations,
        components,
        tracked_by_component,
        branch_boundaries,
    ):
        parent_by_component = {}
        contexts = {}
        affiliate_relations = sorted(
            (
                relation
                for relation in relations
                if relation.relation_type in AFFILIATE_RELATIONS
            ),
            key=lambda relation: (
                relation.relation_type not in STRONG_AFFILIATE_RELATIONS,
                _media_id_key(relation.source_media_id),
                _media_id_key(relation.target_media_id),
            ),
        )
        for relation in affiliate_relations:
            parent_id, affiliate_id = self._affiliate_orientation(relation)
            parent_component = components.find(parent_id)
            affiliate_component = components.find(affiliate_id)
            if parent_component == affiliate_component:
                continue
            if frozenset((parent_id, affiliate_id)) in branch_boundaries:
                continue
            parent_tracked = tracked_by_component.get(parent_component, set())
            affiliate_tracked = tracked_by_component.get(affiliate_component, set())
            if parent_tracked and affiliate_tracked:
                previous = parent_by_component.get(affiliate_component)
                if previous is None:
                    parent_by_component[affiliate_component] = parent_component
                elif previous != parent_component:
                    parent_by_component.pop(affiliate_component, None)
                continue
            if affiliate_tracked and not parent_tracked:
                contexts.setdefault(
                    affiliate_component,
                    (parent_id, relation.relation_type),
                )
        return parent_by_component, contexts

    @staticmethod
    def _affiliate_orientation(relation: AnimeRelation):
        return relation.source_media_id, relation.target_media_id

    @staticmethod
    def _collapsed_component(component_id, parent_by_component):
        visited = set()
        while component_id in parent_by_component and component_id not in visited:
            visited.add(component_id)
            component_id = parent_by_component[component_id]
        return component_id

    @staticmethod
    def _group_context(
        *,
        included_components,
        branch_contexts,
        affiliate_contexts,
    ):
        branch = {
            branch_contexts[component_id]
            for component_id in included_components
            if component_id in branch_contexts
        }
        if len(branch) == 1:
            return branch.pop()
        affiliate = {
            affiliate_contexts[component_id]
            for component_id in included_components
            if component_id in affiliate_contexts
        }
        return affiliate.pop() if len(affiliate) == 1 else None

    @staticmethod
    def _group_kind(*, member_ids, included_components, context):
        if context and context[1] == "spin_off":
            return "spin_off"
        if context and context[1] in {"alternative_version", "alternative_setting"}:
            return "alternative_branch"
        if context and context[1] in AFFILIATE_RELATIONS:
            return "satellite"
        if len(member_ids) > 1 or len(included_components) > 1:
            return "main_continuity"
        return "singleton"

    def _order_members(self, *, member_ids, relations, nodes):
        continuity_relations = [
            relation
            for relation in relations
            if relation.relation_type in CONTINUITY_RELATIONS
            and relation.source_media_id in member_ids
            and relation.target_media_id in member_ids
        ]
        predecessors = {media_id: set() for media_id in member_ids}
        successors = {media_id: set() for media_id in member_ids}
        for relation in continuity_relations:
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
        remaining = sorted(
            member_ids - set(ordered),
            key=lambda media_id: _node_key(nodes[media_id]),
        )
        return (*ordered, *remaining)

    @staticmethod
    def _display_media_id(*, ordered_members, nodes):
        for media_id in ordered_members:
            if nodes[media_id].media_type.lower() in {"tv", "ona"}:
                return media_id
        return ordered_members[0]


def _node_key(node):
    return (
        node.start_date is None,
        node.start_date,
        _media_id_key(node.media_id),
    )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
