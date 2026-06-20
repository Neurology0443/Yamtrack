"""Refresh orchestration for persisted Anime Series View projections."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)
from app.services.anime_series_view_projection_persistence import (
    AnimeSeriesViewProjectionPersistenceService,
)
from app.services.anime_series_view_rules import (
    BRANCH_BOUNDARY_RELATIONS,
    CONTINUITY_RELATIONS,
    GROUPABLE_RELATIONS,
    PROJECTION_RELEVANT_RELATIONS,
)
from app.services.anime_tracking import bulk_mal_anime_tracked_ids

logger = logging.getLogger(__name__)
MAX_REANCHOR_ATTEMPTS = 6


@dataclass
class AnimeSeriesViewRefreshStats:
    """Aggregate counters for one refresh request."""

    snapshots_considered: int = 0
    snapshots_refreshed: int = 0
    snapshots_skipped: int = 0
    groups_projected: int = 0
    memberships_recorded: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_deleted: int = 0
    errors: int = 0


class AnimeSeriesViewProjectionRefreshService:
    """Build snapshots, project tracked IDs, and persist scoped memberships."""

    def __init__(
        self,
        *,
        snapshot_service=None,
        projection_builder=None,
        persistence_service=None,
        tracked_ids_fetcher=None,
    ):
        """Initialize refresh dependencies for production or focused tests."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()
        self.projection_builder = (
            projection_builder or AnimeSeriesViewProjectionBuilder()
        )
        self.persistence_service = (
            persistence_service
            or AnimeSeriesViewProjectionPersistenceService()
        )
        self.tracked_ids_fetcher = (
            tracked_ids_fetcher or bulk_mal_anime_tracked_ids
        )

    def refresh_for_media_ids(
        self,
        *,
        user,
        media_ids,
        refresh_cache=False,
        dry_run=False,
    ) -> AnimeSeriesViewRefreshStats:
        """Refresh each distinct snapshot domain affected by the media IDs."""
        normalized_ids = sorted(
            {
                str(media_id).strip()
                for media_id in media_ids
                if media_id is not None and str(media_id).strip()
            },
            key=_media_id_key,
        )
        stats = AnimeSeriesViewRefreshStats(
            snapshots_considered=len(normalized_ids),
        )
        seen_scopes = set()
        for media_id in normalized_ids:
            try:
                snapshot = self._resolve_projection_snapshot(
                    requested_media_id=media_id,
                    refresh_cache=refresh_cache,
                )
                scope = frozenset(str(value) for value in snapshot.nodes_by_media_id)
                if scope in seen_scopes:
                    stats.snapshots_skipped += 1
                    continue
                seen_scopes.add(scope)
                tracked_ids = self.tracked_ids_fetcher(
                    user_id=user.id,
                    media_ids=scope,
                )
                projection = self.projection_builder.build(
                    snapshot=snapshot,
                    tracked_media_ids=tracked_ids,
                )
                persistence_stats = self.persistence_service.persist(
                    user=user,
                    projection=projection,
                    scope_media_ids=scope,
                    dry_run=dry_run,
                )
                logger.debug(
                    "Anime Series View snapshot projected",
                    extra={
                        "user_id": user.id,
                        "requested_media_id": media_id,
                        "scope_size": len(scope),
                        "tracked_ids_count": len(tracked_ids),
                        "groups_count": len(projection.groups),
                        "dry_run": dry_run,
                    },
                )
            except Exception:
                stats.errors += 1
                stats.snapshots_skipped += 1
                logger.exception(
                    "Anime Series View projection refresh failed",
                    extra={
                        "user_id": user.id,
                        "media_id": media_id,
                        "dry_run": dry_run,
                    },
                )
                continue

            stats.snapshots_refreshed += 1
            stats.groups_projected += len(projection.groups)
            stats.memberships_recorded += persistence_stats.memberships_recorded
            stats.memberships_created += persistence_stats.memberships_created
            stats.memberships_updated += persistence_stats.memberships_updated
            stats.memberships_deleted += persistence_stats.memberships_deleted
        return stats

    def _resolve_projection_snapshot(
        self,
        *,
        requested_media_id,
        refresh_cache,
    ):
        requested_media_id = str(requested_media_id)
        initial_snapshot = self.snapshot_service.build(
            requested_media_id,
            refresh_cache=refresh_cache,
        )
        initial_scope = {
            str(media_id) for media_id in initial_snapshot.nodes_by_media_id
        }
        if requested_media_id not in initial_scope:
            message = (
                "Anime Series View snapshot does not contain requested media ID"
            )
            raise ValueError(message)
        if self._snapshot_is_sufficient(
            snapshot=initial_snapshot,
            requested_media_id=requested_media_id,
        ):
            return initial_snapshot

        for reanchor_media_id in self._projection_reanchor_candidates(
            initial_snapshot
        )[:MAX_REANCHOR_ATTEMPTS]:
            try:
                candidate_snapshot = self.snapshot_service.build(
                    reanchor_media_id,
                    refresh_cache=refresh_cache,
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Anime Series View optional reanchor build failed",
                    extra={
                        "requested_media_id": requested_media_id,
                        "reanchor_media_id": reanchor_media_id,
                    },
                    exc_info=True,
                )
                continue
            if self._candidate_dominates_initial_snapshot(
                initial_snapshot=initial_snapshot,
                candidate_snapshot=candidate_snapshot,
                requested_media_id=requested_media_id,
                reanchor_media_id=reanchor_media_id,
            ):
                chosen_scope = {
                    str(media_id)
                    for media_id in candidate_snapshot.nodes_by_media_id
                }
                logger.debug(
                    "Anime Series View projection snapshot reanchored",
                    extra={
                        "requested_media_id": requested_media_id,
                        "original_root": initial_snapshot.root_node.media_id,
                        "chosen_root": candidate_snapshot.root_node.media_id,
                        "original_scope_size": len(initial_scope),
                        "chosen_scope_size": len(chosen_scope),
                        "original_has_series_line": bool(
                            initial_snapshot.series_line
                        ),
                        "chosen_has_series_line": bool(
                            candidate_snapshot.series_line
                        ),
                        "reanchor_media_id": reanchor_media_id,
                    },
                )
                return candidate_snapshot
        return initial_snapshot

    @staticmethod
    def _snapshot_is_sufficient(*, snapshot, requested_media_id):
        scope = {str(media_id) for media_id in snapshot.nodes_by_media_id}
        return (
            str(requested_media_id) in scope
            and bool(snapshot.series_line)
            and _relevant_escaping_relation_count(snapshot) == 0
        )

    @staticmethod
    def _projection_reanchor_candidates(snapshot):
        inside_ids = {
            str(media_id) for media_id in snapshot.nodes_by_media_id
        }
        candidate_priorities = {}

        if not snapshot.series_line:
            root_media_id = str(snapshot.root_node.media_id)
            for media_id, node in snapshot.nodes_by_media_id.items():
                normalized_id = str(media_id)
                if (
                    normalized_id != root_media_id
                    and str(node.media_type).lower() in {"tv", "ona"}
                ):
                    candidate_priorities[normalized_id] = 0

        for relation in snapshot.all_normalized_relations:
            relation_type = str(relation.relation_type)
            if relation_type not in PROJECTION_RELEVANT_RELATIONS:
                continue
            source_id = str(relation.source_media_id)
            target_id = str(relation.target_media_id)
            source_inside = source_id in inside_ids
            target_inside = target_id in inside_ids
            if source_inside == target_inside:
                continue
            outside_id = target_id if source_inside else source_id
            if relation_type in CONTINUITY_RELATIONS:
                priority = 1
            elif relation_type in GROUPABLE_RELATIONS:
                priority = 2
            elif relation_type in BRANCH_BOUNDARY_RELATIONS:
                priority = 3
            else:  # pragma: no cover - exhaustive by shared constants
                continue
            candidate_priorities[outside_id] = min(
                candidate_priorities.get(outside_id, priority),
                priority,
            )

        return tuple(
            sorted(
                candidate_priorities,
                key=lambda media_id: (
                    candidate_priorities[media_id],
                    _media_id_key(media_id),
                ),
            )
        )

    @staticmethod
    def _candidate_dominates_initial_snapshot(
        *,
        initial_snapshot,
        candidate_snapshot,
        requested_media_id,
        reanchor_media_id,
    ):
        initial_scope = {
            str(media_id) for media_id in initial_snapshot.nodes_by_media_id
        }
        candidate_scope = {
            str(media_id) for media_id in candidate_snapshot.nodes_by_media_id
        }
        requested_media_id = str(requested_media_id)
        reanchor_media_id = str(reanchor_media_id)
        if (
            requested_media_id not in candidate_scope
            or not candidate_snapshot.series_line
            or reanchor_media_id not in candidate_scope
        ):
            return False

        candidate_series_ids = {
            str(node.media_id) for node in candidate_snapshot.series_line
        }
        has_series_anchor = (
            reanchor_media_id in candidate_series_ids
            or str(candidate_snapshot.canonical_root_media_id)
            in candidate_series_ids
            or str(candidate_snapshot.root_node.media_id)
            in candidate_series_ids
        )
        if not has_series_anchor:
            return False
        initial_relevant_ids = _projection_relevant_component_ids(
            snapshot=initial_snapshot,
            seed_media_id=requested_media_id,
        )
        if not initial_relevant_ids <= candidate_scope:
            return False
        candidate_is_more_informative = (
            len(candidate_scope) > len(initial_scope)
            or not initial_snapshot.series_line
        )
        if not candidate_is_more_informative:
            return False

        initial_escaping = _relevant_escaping_relation_count(initial_snapshot)
        candidate_escaping = _relevant_escaping_relation_count(
            candidate_snapshot
        )
        return not (
            initial_snapshot.series_line
            and candidate_escaping > initial_escaping
        )

    def refresh_for_media_id(self, *, user, media_id, **kwargs):
        """Refresh a single affected MAL anime ID."""
        return self.refresh_for_media_ids(
            user=user,
            media_ids=[media_id],
            **kwargs,
        )


def refresh_anime_series_view_best_effort(*, user, media_ids) -> None:
    """Run a collection-triggered refresh without breaking the primary change."""
    try:
        stats = AnimeSeriesViewProjectionRefreshService().refresh_for_media_ids(
            user=user,
            media_ids=media_ids,
        )
        if stats.errors:
            logger.error(
                "Anime Series View refresh completed with errors",
                extra={
                    "user_id": user.id,
                    "media_ids": sorted(map(str, media_ids), key=_media_id_key),
                    "errors": stats.errors,
                },
            )
    except Exception:
        logger.exception(
            "Unexpected Anime Series View refresh failure",
            extra={"user_id": user.id, "media_ids": list(media_ids)},
        )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)


def _relevant_escaping_relation_count(snapshot):
    inside_ids = {str(media_id) for media_id in snapshot.nodes_by_media_id}
    escaping_relations = {
        (
            str(relation.source_media_id),
            str(relation.target_media_id),
            str(relation.relation_type),
        )
        for relation in snapshot.all_normalized_relations
        if str(relation.relation_type) in PROJECTION_RELEVANT_RELATIONS
        and (
            (str(relation.source_media_id) in inside_ids)
            != (str(relation.target_media_id) in inside_ids)
        )
    }
    return len(escaping_relations)


def _projection_relevant_component_ids(*, snapshot, seed_media_id):
    inside_ids = {str(media_id) for media_id in snapshot.nodes_by_media_id}
    seed_media_id = str(seed_media_id)
    if seed_media_id not in inside_ids:
        return set()

    adjacency = {media_id: set() for media_id in inside_ids}
    for relation in snapshot.all_normalized_relations:
        if str(relation.relation_type) not in PROJECTION_RELEVANT_RELATIONS:
            continue
        source_id = str(relation.source_media_id)
        target_id = str(relation.target_media_id)
        if source_id in inside_ids and target_id in inside_ids:
            adjacency[source_id].add(target_id)
            adjacency[target_id].add(source_id)

    seen = {seed_media_id}
    stack = [seed_media_id]
    while stack:
        current = stack.pop()
        for neighbor in adjacency[current]:
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen
