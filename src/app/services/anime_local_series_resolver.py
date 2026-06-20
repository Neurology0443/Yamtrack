"""Pure resolution of tracked MAL anime into stable local series groups."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.anime_local_series_branch_context import (
    AnimeLocalSeriesBranchContextProjector,
)

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
    from app.services.anime_franchise_types import AnimeNode, AnimeRelation


CONTINUITY_RELATIONS = frozenset({"prequel", "sequel"})
AFFILIATE_RELATIONS = frozenset(
    {"side_story", "parent_story", "summary", "full_story"}
)
BRANCH_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting"}
)
AFFILIATE_MEDIA_TYPES = frozenset({"special", "ova", "tv_special"})
IGNORED_RELATIONS = frozenset({"other", "character"})
PRIMARY_DISPLAY_MEDIA_TYPES = frozenset({"tv", "ona"})


@dataclass(frozen=True)
class AnimeLocalSeriesGroup:
    """One persistable logical group containing tracked media only."""

    root_media_id: str
    group_kind: str
    member_media_ids: tuple[str, ...]
    display_media_id: str = ""
    context_parent_media_id: str | None = None
    context_relation_type: str | None = None


@dataclass(frozen=True)
class AnimeLocalSeriesResolution:
    """Deterministic resolver output."""

    groups: tuple[AnimeLocalSeriesGroup, ...]
    resolver_version: str


class _Components:
    def __init__(self, media_ids):
        self.parent = {media_id: media_id for media_id in media_ids}

    def find(self, media_id):
        parent = self.parent[media_id]
        if parent != media_id:
            self.parent[media_id] = self.find(parent)
        return self.parent[media_id]

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        keep, merge = sorted((left_root, right_root), key=_media_id_key)
        self.parent[merge] = keep


class AnimeLocalSeriesResolver:
    """Resolve a complete franchise snapshot without external side effects."""

    resolver_version = "v1"

    def __init__(self, branch_context_projector=None):
        """Create the resolver with an optional branch-context projector."""
        self.branch_context_projector = (
            branch_context_projector or AnimeLocalSeriesBranchContextProjector()
        )

    def resolve(
        self,
        *,
        snapshot: AnimeFranchiseSnapshot,
        tracked_media_ids,
    ) -> AnimeLocalSeriesResolution:
        """Group only tracked IDs while using every snapshot node as context."""
        nodes = snapshot.nodes_by_media_id
        tracked_ids = {
            str(media_id)
            for media_id in tracked_media_ids
            if str(media_id) in nodes
        }
        if not tracked_ids:
            return AnimeLocalSeriesResolution((), self.resolver_version)

        relations = self._relations(snapshot)
        components = _Components(nodes)
        direct_boundaries = {
            frozenset((relation.source_media_id, relation.target_media_id))
            for relation in relations
            if relation.relation_type in BRANCH_RELATIONS
        }

        for relation in relations:
            if relation.relation_type not in CONTINUITY_RELATIONS:
                continue
            if self._would_cross_boundary(
                components=components,
                left_media_id=relation.source_media_id,
                right_media_id=relation.target_media_id,
                boundaries=direct_boundaries,
            ):
                continue
            components.union(relation.source_media_id, relation.target_media_id)

        component_members = self._component_members(nodes, components)
        affiliate_context = self._attach_affiliates(
            nodes=nodes,
            relations=relations,
            components=components,
            component_members=component_members,
            direct_boundaries=direct_boundaries,
        )
        component_members = self._component_members(nodes, components)
        branch_context_facts = self.branch_context_projector.project(snapshot)
        branch_context = self._branch_contexts(
            branch_context_facts=branch_context_facts,
            snapshot=snapshot,
            components=components,
        )

        groups = []
        for component_id, all_member_ids in component_members.items():
            member_ids = tracked_ids & all_member_ids
            if not member_ids:
                continue
            context = branch_context.get(component_id) or affiliate_context.get(
                component_id
            )
            root_media_id = self._root_media_id(
                snapshot=snapshot,
                relations=relations,
                member_ids=member_ids,
            )
            ordered_member_ids = tuple(
                self._ordered_members(
                    snapshot=snapshot,
                    member_ids=member_ids,
                    root_media_id=root_media_id,
                )
            )
            groups.append(
                AnimeLocalSeriesGroup(
                    root_media_id=root_media_id,
                    group_kind=self._group_kind(
                        member_ids=member_ids,
                        context=context,
                    ),
                    member_media_ids=ordered_member_ids,
                    display_media_id=self._select_display_media_id(
                        snapshot=snapshot,
                        root_media_id=root_media_id,
                        member_media_ids=ordered_member_ids,
                    ),
                    context_parent_media_id=context[0] if context else None,
                    context_relation_type=context[1] if context else None,
                )
            )

        groups.sort(
            key=lambda group: self._node_sort_key(
                snapshot.nodes_by_media_id[group.root_media_id]
            )
        )
        return AnimeLocalSeriesResolution(tuple(groups), self.resolver_version)

    def _attach_affiliates(  # noqa: C901, PLR0912
        self,
        *,
        nodes,
        relations,
        components,
        component_members,
        direct_boundaries,
    ):
        candidates = defaultdict(list)
        for relation in relations:
            if relation.relation_type in IGNORED_RELATIONS | BRANCH_RELATIONS:
                continue
            source_component = components.find(relation.source_media_id)
            target_component = components.find(relation.target_media_id)
            if source_component == target_component:
                continue
            if (
                frozenset((relation.source_media_id, relation.target_media_id))
                in direct_boundaries
            ):
                continue
            if not self._is_affiliate_edge(relation, nodes):
                continue

            source_is_satellite = self._is_satellite_component(
                component_members[source_component],
                nodes,
            )
            target_is_satellite = self._is_satellite_component(
                component_members[target_component],
                nodes,
            )
            if source_is_satellite == target_is_satellite:
                if len(component_members[source_component]) == 1:
                    source_is_satellite = True
                elif len(component_members[target_component]) == 1:
                    target_is_satellite = True
                else:
                    continue

            if source_is_satellite:
                satellite_component = source_component
                parent_component = target_component
                parent_media_id = relation.target_media_id
            else:
                satellite_component = target_component
                parent_component = source_component
                parent_media_id = relation.source_media_id
            candidates[satellite_component].append(
                (
                    self._affiliate_priority(relation.relation_type),
                    _media_id_key(parent_media_id),
                    parent_component,
                    parent_media_id,
                    relation.relation_type,
                )
            )

        contexts = {}
        for satellite_component in sorted(candidates, key=_media_id_key):
            candidate = min(candidates[satellite_component])
            parent_component, parent_media_id, relation_type = candidate[2:]
            current_satellite = components.find(satellite_component)
            current_parent = components.find(parent_component)
            if current_satellite == current_parent:
                continue
            if self._would_cross_boundary(
                components=components,
                left_media_id=current_satellite,
                right_media_id=current_parent,
                boundaries=direct_boundaries,
            ):
                continue
            components.union(current_satellite, current_parent)
            merged_component = components.find(current_parent)
            contexts[merged_component] = (parent_media_id, relation_type)
        return contexts

    def _branch_contexts(
        self,
        *,
        branch_context_facts,
        snapshot,
        components,
    ):
        """Attach branch contexts already oriented by the UI projection."""
        contexts = {}
        for context in branch_context_facts:
            parent_media_id = str(context.parent_media_id)
            branch_media_id = str(context.branch_media_id)
            if parent_media_id not in snapshot.nodes_by_media_id:
                continue
            if branch_media_id not in snapshot.nodes_by_media_id:
                continue

            parent_component = components.find(parent_media_id)
            branch_component = components.find(branch_media_id)
            if parent_component == branch_component:
                continue
            contexts.setdefault(
                branch_component,
                (parent_media_id, context.relation_type),
            )
        return contexts

    def _root_media_id(self, *, snapshot, relations, member_ids):
        incoming = defaultdict(set)
        outgoing = defaultdict(set)
        for relation in relations:
            if relation.relation_type not in CONTINUITY_RELATIONS:
                continue
            earlier, later = self._continuity_direction(relation)
            if earlier in member_ids and later in member_ids:
                outgoing[earlier].add(later)
                incoming[later].add(earlier)
        roots = {
            media_id
            for media_id in member_ids
            if outgoing[media_id] and not incoming[media_id]
        }
        candidates = roots or member_ids
        return min(
            candidates,
            key=lambda media_id: self._node_sort_key(
                snapshot.nodes_by_media_id[media_id]
            ),
        )

    def _ordered_members(self, *, snapshot, member_ids, root_media_id):
        return [
            root_media_id,
            *sorted(
                member_ids - {root_media_id},
                key=lambda media_id: self._node_sort_key(
                    snapshot.nodes_by_media_id[media_id]
                ),
            ),
        ]

    def _select_display_media_id(
        self,
        *,
        snapshot,
        root_media_id,
        member_media_ids,
    ):
        """Choose the tracked entry that best represents a logical series."""
        members = tuple(str(media_id) for media_id in member_media_ids)
        nodes = snapshot.nodes_by_media_id
        primary_candidates = [
            media_id
            for media_id in members
            if media_id in nodes
            and nodes[media_id].media_type in PRIMARY_DISPLAY_MEDIA_TYPES
        ]
        if primary_candidates:
            series_order = {
                str(node.media_id): index
                for index, node in enumerate(snapshot.series_line)
            }
            return min(
                primary_candidates,
                key=lambda media_id: (
                    series_order.get(media_id, 10**9),
                    self._node_sort_key(nodes[media_id]),
                ),
            )
        if str(root_media_id) in members:
            return str(root_media_id)
        return members[0] if members else str(root_media_id)

    @staticmethod
    def _relations(snapshot):
        nodes = snapshot.nodes_by_media_id
        relations = {
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
            relations[key]
            for key in sorted(
                relations,
                key=lambda key: (
                    _media_id_key(key[0]),
                    _media_id_key(key[1]),
                    key[2],
                ),
            )
        ]

    @staticmethod
    def _would_cross_boundary(
        *,
        components,
        left_media_id,
        right_media_id,
        boundaries,
    ):
        left_root = components.find(left_media_id)
        right_root = components.find(right_media_id)
        if left_root == right_root:
            return False
        merging_roots = {left_root, right_root}
        return any(
            {
                components.find(boundary_media_id)
                for boundary_media_id in boundary
            }
            == merging_roots
            for boundary in boundaries
        )

    @staticmethod
    def _component_members(nodes, components):
        members = defaultdict(set)
        for media_id in nodes:
            members[components.find(media_id)].add(media_id)
        return members

    @staticmethod
    def _is_affiliate_edge(relation: AnimeRelation, nodes) -> bool:
        return relation.relation_type in AFFILIATE_RELATIONS or bool(
            {
                nodes[relation.source_media_id].media_type,
                nodes[relation.target_media_id].media_type,
            }
            & AFFILIATE_MEDIA_TYPES
        )

    @staticmethod
    def _is_satellite_component(member_ids, nodes) -> bool:
        return all(
            nodes[media_id].media_type in AFFILIATE_MEDIA_TYPES
            for media_id in member_ids
        )

    @staticmethod
    def _affiliate_priority(relation_type):
        priorities = {
            "parent_story": 0,
            "side_story": 1,
            "full_story": 2,
            "summary": 3,
        }
        return priorities.get(relation_type, 4)

    @staticmethod
    def _continuity_direction(relation):
        if relation.relation_type == "prequel":
            return relation.target_media_id, relation.source_media_id
        return relation.source_media_id, relation.target_media_id

    @staticmethod
    def _group_kind(*, member_ids, context):
        if context:
            relation_type = context[1]
            if relation_type == "spin_off":
                return "spin_off"
            if relation_type in {"alternative_version", "alternative_setting"}:
                return "alternative_branch"
            if len(member_ids) == 1:
                return "affiliate"
        return "main_continuity" if len(member_ids) > 1 else "singleton"

    @staticmethod
    def _node_sort_key(node: AnimeNode):
        return (
            node.start_date.isoformat() if node.start_date else "9999-12-31",
            _media_id_key(node.media_id),
        )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
