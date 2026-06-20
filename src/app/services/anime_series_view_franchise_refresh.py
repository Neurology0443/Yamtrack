"""Persist the simple franchise-root read model for Anime Series View."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from app.models import Anime, AnimeSeriesViewMembership, MediaTypes, Sources
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_series_view_franchise_projection import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
    resolve_series_line_root,
)
from app.services.anime_series_view_refresh_queue import normalize_media_ids

logger = logging.getLogger(__name__)


@dataclass
class AnimeSeriesViewFranchiseRefreshStats:
    """Counters produced by one projection refresh."""

    requested: int = 0
    snapshots_built: int = 0
    snapshots_skipped: int = 0
    franchise_memberships_created: int = 0
    franchise_memberships_updated: int = 0
    singleton_memberships_created: int = 0
    singleton_memberships_updated: int = 0
    memberships_deleted: int = 0
    errors: int = 0


class AnimeSeriesViewFranchiseRefreshService:
    """Build canonical snapshots and persist one membership per tracked anime."""

    def __init__(self, *, snapshot_service=None):
        """Initialize with the canonical snapshot service."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()

    def refresh_for_media_ids(
        self,
        *,
        user,
        media_ids,
        refresh_cache=False,
        dry_run=False,
    ) -> AnimeSeriesViewFranchiseRefreshStats:
        """Refresh all distinct snapshot scopes reached by the requested IDs."""
        normalized_ids = normalize_media_ids(media_ids)
        stats = AnimeSeriesViewFranchiseRefreshStats(requested=len(normalized_ids))

        if not dry_run:
            stats.memberships_deleted += self.remove_direct_memberships(
                user=user,
                media_ids=normalized_ids,
            )

        processed_scopes: set[frozenset[str]] = set()
        for media_id in normalized_ids:
            try:
                snapshot = self.snapshot_service.build(
                    media_id,
                    refresh_cache=refresh_cache,
                )
                stats.snapshots_built += 1
            except Exception:
                stats.errors += 1
                stats.snapshots_skipped += 1
                logger.exception(
                    "Failed to build Anime Series View franchise snapshot",
                    extra={"user_id": user.id, "media_id": media_id},
                )
                continue

            scope_media_ids = {
                str(scope_media_id) for scope_media_id in snapshot.nodes_by_media_id
            }
            scope_key = frozenset(scope_media_ids)
            if not scope_key or scope_key in processed_scopes:
                stats.snapshots_skipped += 1
                continue
            processed_scopes.add(scope_key)

            scope_stats = AnimeSeriesViewFranchiseRefreshStats()
            try:
                self._persist_scope(
                    user=user,
                    snapshot=snapshot,
                    scope_media_ids=scope_media_ids,
                    stats=scope_stats,
                    dry_run=dry_run,
                )
            except Exception:
                stats.errors += 1
                logger.exception(
                    "Failed to persist Anime Series View franchise scope",
                    extra={
                        "user_id": user.id,
                        "media_id": media_id,
                        "scope_media_ids": sorted(scope_media_ids),
                    },
                )
                continue

            for field_name in (
                "franchise_memberships_created",
                "franchise_memberships_updated",
                "singleton_memberships_created",
                "singleton_memberships_updated",
                "memberships_deleted",
            ):
                setattr(
                    stats,
                    field_name,
                    getattr(stats, field_name) + getattr(scope_stats, field_name),
                )

        return stats

    def remove_direct_memberships(self, *, user, media_ids):
        """Delete requested rows before rebuilding, which also cleans deletions."""
        normalized_ids = normalize_media_ids(media_ids)
        if not normalized_ids:
            return 0

        deleted, _ = AnimeSeriesViewMembership.objects.filter(
            user=user,
            media_id__in=normalized_ids,
        ).delete()
        return deleted

    @transaction.atomic
    def _persist_scope(
        self,
        *,
        user,
        snapshot,
        scope_media_ids,
        stats,
        dry_run,
    ):
        tracked_anime = list(
            Anime.objects.select_related("item").filter(
                user=user,
                item__source=Sources.MAL.value,
                item__media_type=MediaTypes.ANIME.value,
                item__media_id__in=scope_media_ids,
            )
        )
        tracked_ids = {anime.item.media_id for anime in tracked_anime}
        existing_memberships = {
            membership.media_id: membership
            for membership in AnimeSeriesViewMembership.objects.filter(
                user=user,
                media_id__in=scope_media_ids,
            )
        }

        stale_ids = set(existing_memberships) - tracked_ids
        if dry_run:
            stats.memberships_deleted += len(stale_ids)
        elif stale_ids:
            deleted, _ = AnimeSeriesViewMembership.objects.filter(
                user=user,
                media_id__in=stale_ids,
            ).delete()
            stats.memberships_deleted += deleted

        if not tracked_anime:
            return

        root = resolve_series_line_root(snapshot)
        for anime in tracked_anime:
            media_id = anime.item.media_id
            if root is not None:
                defaults = self._franchise_defaults(root)
                created_field = "franchise_memberships_created"
                updated_field = "franchise_memberships_updated"
            else:
                defaults = self._singleton_defaults(anime.item)
                created_field = "singleton_memberships_created"
                updated_field = "singleton_memberships_updated"

            if dry_run:
                field_name = (
                    updated_field if media_id in existing_memberships else created_field
                )
                setattr(stats, field_name, getattr(stats, field_name) + 1)
                continue

            _, created = AnimeSeriesViewMembership.objects.update_or_create(
                user=user,
                media_id=media_id,
                defaults=defaults,
            )
            field_name = created_field if created else updated_field
            setattr(stats, field_name, getattr(stats, field_name) + 1)

    @staticmethod
    def _franchise_defaults(root):
        return {
            "root_media_id": root.media_id,
            "display_media_id": root.media_id,
            "display_title": root.title,
            "display_image": root.image,
            "display_media_type": root.media_type,
            "display_start_date": root.start_date,
            "group_kind": GROUP_KIND_FRANCHISE,
            "projection_version": PROJECTION_VERSION,
        }

    @staticmethod
    def _singleton_defaults(local_item):
        return {
            "root_media_id": local_item.media_id,
            "display_media_id": local_item.media_id,
            "display_title": local_item.title,
            "display_image": local_item.image,
            "display_media_type": local_item.media_type,
            "display_start_date": getattr(local_item, "start_date", None),
            "group_kind": GROUP_KIND_SINGLETON,
            "projection_version": PROJECTION_VERSION,
        }
