"""Pure, reusable projection builder for Anime Series View franchises."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date

from app.anime_series_view_constants import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
)
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_series_view_rules import (
    SERIES_VIEW_BOUNDARY_ALTERNATIVE_RELATIONS,
    SERIES_VIEW_CONTINUITY_RELATIONS,
    SERIES_VIEW_GROUPABLE_RELATIONS,
    SERIES_VIEW_INDEPENDENT_CONTINUITY_MEDIA_TYPES,
    SERIES_VIEW_REROOT_RELATION_PRIORITY,
    SERIES_VIEW_ROOT_MEDIA_TYPES,
    SERIES_VIEW_STRONG_REROOT_RELATIONS,
)


@dataclass(frozen=True)
class AnimeSeriesViewProjectionRoot:
    """Stable display metadata for one projected franchise root."""

    media_id: str
    title: str
    image: str
    media_type: str
    start_date: date | None
    alternative_title_en: str = ""


@dataclass(frozen=True)
class AnimeSeriesViewProjection:
    """A persistable projection or a conservative unresolved outcome."""

    seed_media_id: str
    root: AnimeSeriesViewProjectionRoot | None
    member_media_ids: tuple[str, ...]
    group_kind: str | None
    projection_version: str
    is_rerooted: bool = False
    reroot_from_media_id: str | None = None
    reroot_relation_type: str | None = None
    is_confident: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class _RootCandidate:
    media_id: str
    relation_type: str
    is_in_series_line: bool


class AnimeSeriesViewProjectionBuilder:
    """Build one-card canonical projections with at most one controlled reroot."""

    def __init__(self, *, snapshot_service=None):
        """Initialize with the canonical snapshot service."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()

    def build(
        self,
        seed_media_id,
        *,
        refresh_cache=False,
    ) -> AnimeSeriesViewProjection:
        """Build a confident franchise/singleton or an unresolved projection."""
        seed_media_id = str(seed_media_id)
        initial_snapshot = self.snapshot_service.build(
            seed_media_id,
            refresh_cache=refresh_cache,
            include_series_view_branch_continuations=True,
        )
        initial_boundary_keys = self._alternative_continuity_boundary_relation_keys(
            initial_snapshot
        )
        initial_component = self._groupable_component(
            initial_snapshot,
            seed_media_id,
            excluded_relation_keys=initial_boundary_keys,
        )
        local_root = self._component_root(initial_snapshot, initial_component)
        candidate = self._select_best_root_candidate(
            initial_snapshot,
            initial_component,
            local_root_media_id=local_root.media_id if local_root else None,
            excluded_relation_keys=initial_boundary_keys,
        )

        if self._should_reroot(
            snapshot=initial_snapshot,
            component_media_ids=initial_component,
            local_root=local_root,
            candidate=candidate,
        ):
            return self._build_rerooted_projection(
                seed_media_id=seed_media_id,
                initial_snapshot=initial_snapshot,
                initial_component=initial_component,
                candidate=candidate,
                refresh_cache=refresh_cache,
            )

        if local_root is not None and self._local_projection_is_confident(
            initial_snapshot,
            initial_component,
            local_root,
            excluded_relation_keys=initial_boundary_keys,
        ):
            return self._franchise_projection(
                seed_media_id=seed_media_id,
                root_node=local_root,
                member_media_ids=initial_component,
            )

        if not self._has_groupable_evidence(
            initial_snapshot,
            initial_component,
            excluded_relation_keys=initial_boundary_keys,
        ):
            return self._singleton_projection(initial_snapshot, seed_media_id)

        return self._unresolved_projection(
            seed_media_id=seed_media_id,
            member_media_ids=initial_component,
            reason="insufficient_groupable_evidence",
        )

    def _build_rerooted_projection(
        self,
        *,
        seed_media_id,
        initial_snapshot,
        initial_component,
        candidate,
        refresh_cache,
    ):
        canonical_snapshot = self.snapshot_service.build(
            candidate.media_id,
            refresh_cache=refresh_cache,
            include_series_view_branch_continuations=True,
        )
        canonical_boundary_keys = self._alternative_continuity_boundary_relation_keys(
            canonical_snapshot
        )
        canonical_root = self._local_root(canonical_snapshot)
        canonical_component = self._groupable_component(
            canonical_snapshot,
            canonical_root.media_id if canonical_root else candidate.media_id,
            excluded_relation_keys=canonical_boundary_keys,
        )
        is_strong = candidate.relation_type in SERIES_VIEW_STRONG_REROOT_RELATIONS
        has_clear_continuity = self._has_clear_continuity(
            canonical_snapshot,
            canonical_component,
            excluded_relation_keys=canonical_boundary_keys,
        )
        weak_snapshot_is_truncated = (
            bool(getattr(canonical_snapshot, "is_truncated", False)) and not is_strong
        )

        component_root = self._component_root(canonical_snapshot, canonical_component)

        if component_root is not None:
            root_node = component_root
        elif is_strong:
            root_node = canonical_snapshot.nodes_by_media_id.get(
                candidate.media_id,
                initial_snapshot.nodes_by_media_id.get(candidate.media_id),
            )
        elif has_clear_continuity and not weak_snapshot_is_truncated:
            root_node = self._oldest_root_node(
                canonical_snapshot,
                canonical_component,
            )
        else:
            return self._unresolved_projection(
                seed_media_id=seed_media_id,
                member_media_ids=initial_component,
                reason="weak_reroot_unconfirmed",
                is_rerooted=True,
                reroot_from_media_id=candidate.media_id,
                reroot_relation_type=candidate.relation_type,
            )

        if root_node is None:
            return self._unresolved_projection(
                seed_media_id=seed_media_id,
                member_media_ids=initial_component,
                reason="reroot_root_missing",
                is_rerooted=True,
                reroot_from_media_id=candidate.media_id,
                reroot_relation_type=candidate.relation_type,
            )

        member_ids = self._normalize_media_ids(
            {*canonical_component, *initial_component, seed_media_id}
        )
        return self._franchise_projection(
            seed_media_id=seed_media_id,
            root_node=root_node,
            member_media_ids=member_ids,
            is_rerooted=True,
            reroot_from_media_id=candidate.media_id,
            reroot_relation_type=candidate.relation_type,
        )

    def _groupable_component(
        self,
        snapshot,
        seed_media_id,
        *,
        excluded_relation_keys=frozenset(),
    ):
        seed_media_id = str(seed_media_id)
        nodes_by_media_id = snapshot.nodes_by_media_id
        if seed_media_id not in nodes_by_media_id:
            return {seed_media_id}

        adjacency = {str(media_id): set() for media_id in nodes_by_media_id}
        for relation in self._candidate_relations(snapshot):
            if relation.relation_type not in SERIES_VIEW_GROUPABLE_RELATIONS:
                continue
            if self._relation_key(relation) in excluded_relation_keys:
                continue
            source_id = str(relation.source_media_id)
            target_id = str(relation.target_media_id)
            if source_id not in adjacency or target_id not in adjacency:
                continue
            adjacency[source_id].add(target_id)
            adjacency[target_id].add(source_id)

        visited = set()
        queue = deque([seed_media_id])
        while queue:
            media_id = queue.popleft()
            if media_id in visited:
                continue
            visited.add(media_id)
            queue.extend(adjacency[media_id] - visited)
        return visited

    def _select_best_root_candidate(
        self,
        snapshot,
        component_media_ids,
        *,
        local_root_media_id=None,
        excluded_relation_keys=frozenset(),
    ):
        series_line_ids = {
            node.media_id for node in getattr(snapshot, "series_line", ())
        }
        candidates = {}
        for relation in self._component_relations(
            snapshot,
            component_media_ids,
            excluded_relation_keys=excluded_relation_keys,
        ):
            for media_id in (
                str(relation.source_media_id),
                str(relation.target_media_id),
            ):
                node = snapshot.nodes_by_media_id.get(media_id)
                if not self._is_root_compatible(node):
                    continue
                candidate = _RootCandidate(
                    media_id=media_id,
                    relation_type=relation.relation_type,
                    is_in_series_line=media_id in series_line_ids,
                )
                current = candidates.get(media_id)
                if current is None or self._candidate_sort_key(
                    candidate,
                    snapshot,
                ) < self._candidate_sort_key(current, snapshot):
                    candidates[media_id] = candidate

        if local_root_media_id and local_root_media_id not in candidates:
            local_node = snapshot.nodes_by_media_id.get(local_root_media_id)
            if self._is_root_compatible(local_node):
                candidates[local_root_media_id] = _RootCandidate(
                    media_id=local_root_media_id,
                    relation_type="sequel",
                    is_in_series_line=True,
                )

        if not candidates:
            return None
        return min(
            candidates.values(),
            key=lambda candidate: self._candidate_sort_key(candidate, snapshot),
        )

    def _should_reroot(
        self,
        *,
        snapshot,
        component_media_ids,
        local_root,
        candidate,
    ):
        if candidate is None:
            return False
        if local_root is None:
            return True
        if candidate.media_id == local_root.media_id:
            return False

        candidate_node = snapshot.nodes_by_media_id[candidate.media_id]
        if candidate.relation_type in SERIES_VIEW_STRONG_REROOT_RELATIONS:
            return True
        if candidate_node.start_date and (
            local_root.start_date is None
            or candidate_node.start_date < local_root.start_date
        ):
            return True
        return (
            candidate.relation_type in {"spin_off", "side_story"}
            and candidate.media_id in component_media_ids
            and candidate_node.media_id != local_root.media_id
            and self._media_type_rank(candidate_node.media_type)
            < self._media_type_rank(local_root.media_type)
        )

    def _local_projection_is_confident(
        self,
        snapshot,
        component_media_ids,
        local_root,
        *,
        excluded_relation_keys=frozenset(),
    ):
        if snapshot.series_line:
            return True
        return (
            local_root.media_type.lower() in SERIES_VIEW_ROOT_MEDIA_TYPES
            and self._has_clear_continuity(
                snapshot,
                component_media_ids,
                excluded_relation_keys=excluded_relation_keys,
            )
        )

    def _has_clear_continuity(
        self,
        snapshot,
        component_media_ids,
        *,
        excluded_relation_keys=frozenset(),
    ):
        return any(
            relation.relation_type in SERIES_VIEW_CONTINUITY_RELATIONS
            for relation in self._component_relations(
                snapshot,
                component_media_ids,
                excluded_relation_keys=excluded_relation_keys,
            )
        )

    def _has_groupable_evidence(
        self,
        snapshot,
        component_media_ids,
        *,
        excluded_relation_keys=frozenset(),
    ):
        return any(
            self._component_relations(
                snapshot,
                component_media_ids,
                excluded_relation_keys=excluded_relation_keys,
            )
        )

    def _oldest_root_node(self, snapshot, component_media_ids):
        candidates = [
            snapshot.nodes_by_media_id[media_id]
            for media_id in component_media_ids
            if self._is_root_compatible(snapshot.nodes_by_media_id.get(media_id))
        ]
        if not candidates:
            return None
        return min(candidates, key=self._node_sort_key)

    def _local_root(self, snapshot):
        if snapshot.series_line:
            return snapshot.series_line[0]
        root_node = snapshot.root_node
        return root_node if self._is_root_compatible(root_node) else None

    def _component_root(self, snapshot, component_media_ids):
        root_node = self._oldest_root_node(snapshot, component_media_ids)
        if root_node is not None:
            return root_node

        component_media_ids = {str(media_id) for media_id in component_media_ids}
        local_root = self._local_root(snapshot)
        if local_root is not None and str(local_root.media_id) in component_media_ids:
            return local_root

        return None

    def _component_relations(
        self,
        snapshot,
        component_media_ids,
        *,
        excluded_relation_keys=frozenset(),
    ):
        component_media_ids = {str(media_id) for media_id in component_media_ids}
        return [
            relation
            for relation in self._candidate_relations(snapshot)
            if relation.relation_type in SERIES_VIEW_GROUPABLE_RELATIONS
            and self._relation_key(relation) not in excluded_relation_keys
            and str(relation.source_media_id) in component_media_ids
            and str(relation.target_media_id) in component_media_ids
        ]

    def _alternative_continuity_boundary_relation_keys(self, snapshot):
        relations = self._candidate_relations(snapshot)
        direct_boundaries = [
            relation
            for relation in relations
            if self._is_independent_alternative_continuity_boundary(
                snapshot,
                relation,
            )
        ]
        external_serial_ids = set()
        series_line_ids = {
            str(node.media_id) for node in getattr(snapshot, "series_line", ())
        }
        for relation in direct_boundaries:
            for media_id in (
                str(relation.source_media_id),
                str(relation.target_media_id),
            ):
                if media_id not in series_line_ids:
                    external_serial_ids.add(media_id)

        return {
            self._relation_key(relation)
            for relation in relations
            if self._is_independent_alternative_continuity_boundary(
                snapshot,
                relation,
            )
            or (
                relation.relation_type in SERIES_VIEW_BOUNDARY_ALTERNATIVE_RELATIONS
                and self._relation_has_external_serial_endpoint(
                    snapshot,
                    relation,
                    external_serial_ids,
                )
            )
        }

    def _relation_has_external_serial_endpoint(
        self,
        snapshot,
        relation,
        external_serial_ids,
    ):
        source = snapshot.nodes_by_media_id.get(str(relation.source_media_id))
        target = snapshot.nodes_by_media_id.get(str(relation.target_media_id))
        if source is None or target is None:
            return False
        if (
            source.media_type.lower()
            not in SERIES_VIEW_INDEPENDENT_CONTINUITY_MEDIA_TYPES
            or target.media_type.lower()
            not in SERIES_VIEW_INDEPENDENT_CONTINUITY_MEDIA_TYPES
        ):
            return False
        return (
            str(source.media_id) in external_serial_ids
            or str(target.media_id) in external_serial_ids
        )

    def _is_independent_alternative_continuity_boundary(
        self,
        snapshot,
        relation,
    ):
        if relation.relation_type not in SERIES_VIEW_BOUNDARY_ALTERNATIVE_RELATIONS:
            return False

        source = snapshot.nodes_by_media_id.get(str(relation.source_media_id))
        target = snapshot.nodes_by_media_id.get(str(relation.target_media_id))
        if source is None or target is None:
            return False
        if not self._is_root_compatible(source) or not self._is_root_compatible(target):
            return False
        if (
            source.media_type.lower()
            not in SERIES_VIEW_INDEPENDENT_CONTINUITY_MEDIA_TYPES
            or target.media_type.lower()
            not in SERIES_VIEW_INDEPENDENT_CONTINUITY_MEDIA_TYPES
        ):
            return False

        series_line_ids = {
            str(node.media_id) for node in getattr(snapshot, "series_line", ())
        }
        if not series_line_ids:
            return False

        source_in_line = str(source.media_id) in series_line_ids
        target_in_line = str(target.media_id) in series_line_ids
        return source_in_line != target_in_line

    @staticmethod
    def _candidate_relations(snapshot):
        relations = []
        seen = set()
        for attribute in (
            "root_story_parent_candidates",
            "no_series_line_secondary_candidates",
            "direct_candidates",
            "all_normalized_relations",
        ):
            for relation in getattr(snapshot, attribute, ()) or ():
                key = AnimeSeriesViewProjectionBuilder._relation_key(relation)
                if key not in seen:
                    seen.add(key)
                    relations.append(relation)
        return relations

    @staticmethod
    def _relation_key(relation):
        return (
            str(relation.source_media_id),
            str(relation.target_media_id),
            relation.relation_type,
        )

    def _candidate_sort_key(self, candidate, snapshot):
        node = snapshot.nodes_by_media_id[candidate.media_id]
        return (
            0 if candidate.relation_type in SERIES_VIEW_STRONG_REROOT_RELATIONS else 1,
            SERIES_VIEW_REROOT_RELATION_PRIORITY[candidate.relation_type],
            self._media_type_rank(node.media_type),
            node.start_date or date.max,
            0 if candidate.is_in_series_line else 1,
            self._media_id_sort_key(candidate.media_id),
        )

    def _singleton_projection(self, snapshot, seed_media_id):
        node = snapshot.nodes_by_media_id.get(seed_media_id, snapshot.root_node)
        return AnimeSeriesViewProjection(
            seed_media_id=seed_media_id,
            root=self._projection_root(node),
            member_media_ids=(seed_media_id,),
            group_kind=GROUP_KIND_SINGLETON,
            projection_version=PROJECTION_VERSION,
        )

    def _unresolved_projection(
        self,
        *,
        seed_media_id,
        member_media_ids,
        reason,
        is_rerooted=False,
        reroot_from_media_id=None,
        reroot_relation_type=None,
    ):
        return AnimeSeriesViewProjection(
            seed_media_id=seed_media_id,
            root=None,
            member_media_ids=self._normalize_media_ids(member_media_ids),
            group_kind=None,
            projection_version=PROJECTION_VERSION,
            is_rerooted=is_rerooted,
            reroot_from_media_id=reroot_from_media_id,
            reroot_relation_type=reroot_relation_type,
            is_confident=False,
            skip_reason=reason,
        )

    def _franchise_projection(
        self,
        *,
        seed_media_id,
        root_node,
        member_media_ids,
        is_rerooted=False,
        reroot_from_media_id=None,
        reroot_relation_type=None,
    ):
        return AnimeSeriesViewProjection(
            seed_media_id=seed_media_id,
            root=self._projection_root(root_node),
            member_media_ids=self._normalize_media_ids(
                {*member_media_ids, seed_media_id}
            ),
            group_kind=GROUP_KIND_FRANCHISE,
            projection_version=PROJECTION_VERSION,
            is_rerooted=is_rerooted,
            reroot_from_media_id=reroot_from_media_id,
            reroot_relation_type=reroot_relation_type,
        )

    @staticmethod
    def _projection_root(node):
        return AnimeSeriesViewProjectionRoot(
            media_id=str(node.media_id),
            title=node.title,
            image=node.image,
            media_type=node.media_type,
            start_date=node.start_date,
            alternative_title_en=node.alternative_title_en or "",
        )

    def _node_sort_key(self, node):
        return (
            self._media_type_rank(node.media_type),
            node.start_date or date.max,
            self._media_id_sort_key(node.media_id),
        )

    @staticmethod
    def _is_root_compatible(node):
        return bool(node and node.media_type.lower() in SERIES_VIEW_ROOT_MEDIA_TYPES)

    @staticmethod
    def _media_type_rank(media_type):
        return {"tv": 0, "ona": 1, "movie": 2, "ova": 3}.get(
            media_type.lower(),
            4,
        )

    def _normalize_media_ids(self, media_ids):
        return tuple(
            sorted(
                {str(media_id) for media_id in media_ids},
                key=self._media_id_sort_key,
            )
        )

    @staticmethod
    def _media_id_sort_key(media_id):
        try:
            return (0, int(media_id))
        except ValueError:
            return (1, str(media_id))
