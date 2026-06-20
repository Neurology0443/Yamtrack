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
from app.services.anime_tracking import bulk_mal_anime_tracked_ids

logger = logging.getLogger(__name__)


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
                snapshot = self.snapshot_service.build(
                    media_id,
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
