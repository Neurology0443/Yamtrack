"""Pure, reusable projection builder for Anime Series View franchises."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_series_view_rules import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
    SERIES_VIEW_GROUPABLE_RELATIONS,
    SERIES_VIEW_REROOT_RELATION_PRIORITY,
    SERIES_VIEW_ROOT_MEDIA_TYPES,
)


@dataclass(frozen=True)
class AnimeSeriesViewProjectionRoot:
    """Stable display metadata for one projected franchise root."""

    media_id: str
    title: str
    image: str
    media_type: str
    start_date: date | None


@dataclass(frozen=True)
class AnimeSeriesViewProjection:
    """A persistable franchise or explicit singleton projection."""

    seed_media_id: str
    root: AnimeSeriesViewProjectionRoot
    member_media_ids: tuple[str, ...]
    group_kind: str
    projection_version: str
    is_rerooted: bool = False
    reroot_from_media_id: str | None = None
    reroot_relation_type: str | None = None


@dataclass(frozen=True)
class _RerootCandidate:
    media_id: str
    relation_type: str


class AnimeSeriesViewProjectionBuilder:
    """Build one-card franchise projections from canonical MAL snapshots."""

    def __init__(self, *, snapshot_service=None):
        """Initialize with the canonical snapshot service."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()

    def build(
        self,
        seed_media_id,
        *,
        refresh_cache=False,
    ) -> AnimeSeriesViewProjection:
        """Build a projection with at most one controlled reroot."""
        seed_media_id = str(seed_media_id)
        initial_snapshot = self.snapshot_service.build(
            seed_media_id,
            refresh_cache=refresh_cache,
        )

        initial_root = self._series_line_root(initial_snapshot)
        if initial_root is not None:
            member_ids = self._member_media_ids(
                initial_snapshot,
                start_media_ids={
                    seed_media_id,
                    *(node.media_id for node in initial_snapshot.series_line),
                },
            )
            return self._franchise_projection(
                seed_media_id=seed_media_id,
                root_node=initial_root,
                member_media_ids=member_ids,
            )

        candidate = self._select_reroot_candidate(
            initial_snapshot,
            seed_media_id=seed_media_id,
        )
        if candidate is None:
            return self._singleton_projection(initial_snapshot, seed_media_id)

        canonical_snapshot = self.snapshot_service.build(
            candidate.media_id,
            refresh_cache=refresh_cache,
        )
        canonical_root = self._series_line_root(canonical_snapshot)
        if canonical_root is None:
            canonical_root = initial_snapshot.nodes_by_media_id[candidate.media_id]

        canonical_member_ids = self._member_media_ids(
            canonical_snapshot,
            start_media_ids={
                candidate.media_id,
                *(node.media_id for node in canonical_snapshot.series_line),
                canonical_root.media_id,
            },
        )
        initial_member_ids = self._member_media_ids(
            initial_snapshot,
            start_media_ids={seed_media_id, candidate.media_id},
        )
        member_ids = self._normalize_media_ids(
            {*canonical_member_ids, *initial_member_ids, seed_media_id}
        )
        return self._franchise_projection(
            seed_media_id=seed_media_id,
            root_node=canonical_root,
            member_media_ids=member_ids,
            is_rerooted=True,
            reroot_from_media_id=candidate.media_id,
            reroot_relation_type=candidate.relation_type,
        )

    def _select_reroot_candidate(self, snapshot, *, seed_media_id):
        candidates = {}
        for relation in self._candidate_relations(snapshot):
            if relation.relation_type not in SERIES_VIEW_GROUPABLE_RELATIONS:
                continue

            candidate_media_id = self._opposite_media_id(
                relation,
                seed_media_id=seed_media_id,
            )
            if candidate_media_id is None:
                continue

            node = snapshot.nodes_by_media_id.get(candidate_media_id)
            if (
                node is None
                or node.media_type.lower() not in SERIES_VIEW_ROOT_MEDIA_TYPES
            ):
                continue

            candidate = _RerootCandidate(
                media_id=str(candidate_media_id),
                relation_type=relation.relation_type,
            )
            current = candidates.get(candidate.media_id)
            if current is None or self._candidate_sort_key(
                candidate,
                snapshot,
            ) < self._candidate_sort_key(current, snapshot):
                candidates[candidate.media_id] = candidate

        if not candidates:
            return None
        return min(
            candidates.values(),
            key=lambda candidate: self._candidate_sort_key(candidate, snapshot),
        )

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
                key = (
                    relation.source_media_id,
                    relation.target_media_id,
                    relation.relation_type,
                )
                if key not in seen:
                    seen.add(key)
                    relations.append(relation)
        return relations

    @staticmethod
    def _opposite_media_id(relation, *, seed_media_id):
        if relation.source_media_id == seed_media_id:
            return str(relation.target_media_id)
        if relation.target_media_id == seed_media_id:
            return str(relation.source_media_id)
        return None

    def _candidate_sort_key(self, candidate, snapshot):
        node = snapshot.nodes_by_media_id[candidate.media_id]
        return (
            SERIES_VIEW_REROOT_RELATION_PRIORITY[candidate.relation_type],
            node.start_date or date.max,
            self._media_id_sort_key(candidate.media_id),
        )

    def _member_media_ids(self, snapshot, *, start_media_ids):
        nodes_by_media_id = snapshot.nodes_by_media_id
        adjacency = {str(media_id): set() for media_id in nodes_by_media_id}
        for relation in getattr(snapshot, "all_normalized_relations", ()) or ():
            if relation.relation_type not in SERIES_VIEW_GROUPABLE_RELATIONS:
                continue
            source_id = str(relation.source_media_id)
            target_id = str(relation.target_media_id)
            if source_id not in nodes_by_media_id or target_id not in nodes_by_media_id:
                continue
            adjacency[source_id].add(target_id)
            adjacency[target_id].add(source_id)

        visited = set()
        queue = deque(
            str(media_id)
            for media_id in start_media_ids
            if str(media_id) in nodes_by_media_id
        )
        while queue:
            media_id = queue.popleft()
            if media_id in visited:
                continue
            visited.add(media_id)
            queue.extend(adjacency.get(media_id, ()) - visited)

        return self._normalize_media_ids(visited)

    def _singleton_projection(self, snapshot, seed_media_id):
        node = snapshot.nodes_by_media_id.get(seed_media_id, snapshot.root_node)
        return AnimeSeriesViewProjection(
            seed_media_id=seed_media_id,
            root=self._projection_root(node),
            member_media_ids=(seed_media_id,),
            group_kind=GROUP_KIND_SINGLETON,
            projection_version=PROJECTION_VERSION,
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
    def _series_line_root(snapshot):
        return snapshot.series_line[0] if snapshot.series_line else None

    @staticmethod
    def _projection_root(node):
        return AnimeSeriesViewProjectionRoot(
            media_id=str(node.media_id),
            title=node.title,
            image=node.image,
            media_type=node.media_type,
            start_date=node.start_date,
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
