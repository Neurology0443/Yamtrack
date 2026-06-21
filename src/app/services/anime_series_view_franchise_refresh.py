"""Persist user memberships from pure Anime Series View projections."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from app.anime_series_view_constants import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
)
from app.models import Anime, AnimeSeriesViewMembership, MediaTypes, Sources
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
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
    """Persist one membership per tracked anime from reusable projections."""

    def __init__(self, *, projection_builder=None):
        """Initialize with the pure projection builder."""
        self.projection_builder = (
            projection_builder or AnimeSeriesViewProjectionBuilder()
        )

    def refresh_for_media_ids(
        self,
        *,
        user,
        media_ids,
        refresh_cache=False,
        dry_run=False,
    ) -> AnimeSeriesViewFranchiseRefreshStats:
        """Refresh valid projections without deleting rows before a successful build."""
        return self._refresh_for_media_ids(
            user=user,
            media_ids=media_ids,
            refresh_cache=refresh_cache,
            dry_run=dry_run,
        )

    def refresh_after_delete(
        self,
        *,
        user,
        media_ids,
        refresh_cache=False,
        dry_run=False,
    ) -> AnimeSeriesViewFranchiseRefreshStats:
        """Remove deleted rows first, then best-effort refresh remaining scopes."""
        normalized_ids = normalize_media_ids(media_ids)
        direct_deleted = 0
        if dry_run:
            direct_deleted = AnimeSeriesViewMembership.objects.filter(
                user=user,
                media_id__in=normalized_ids,
            ).count()
        else:
            direct_deleted = self.remove_direct_memberships(
                user=user,
                media_ids=normalized_ids,
            )

        return self._refresh_for_media_ids(
            user=user,
            media_ids=normalized_ids,
            refresh_cache=refresh_cache,
            dry_run=dry_run,
            direct_deleted=direct_deleted,
        )

    def _refresh_for_media_ids(
        self,
        *,
        user,
        media_ids,
        refresh_cache,
        dry_run,
        direct_deleted=0,
    ):
        normalized_ids = normalize_media_ids(media_ids)
        stats = AnimeSeriesViewFranchiseRefreshStats(
            requested=len(normalized_ids),
            memberships_deleted=direct_deleted,
        )

        processed_projections = set()
        covered_media_ids = set()
        for media_id in normalized_ids:
            if media_id in covered_media_ids:
                stats.snapshots_skipped += 1
                continue

            try:
                projection = self.projection_builder.build(
                    media_id,
                    refresh_cache=refresh_cache,
                )
                stats.snapshots_built += 1
            except Exception:
                stats.errors += 1
                stats.snapshots_skipped += 1
                logger.exception(
                    "Failed to build Anime Series View projection",
                    extra={"user_id": user.id, "media_id": media_id},
                )
                continue

            if not projection.is_confident:
                stats.snapshots_skipped += 1
                logger.info(
                    "Skipping unresolved Anime Series View projection",
                    extra={
                        "user_id": user.id,
                        "media_id": media_id,
                        "skip_reason": projection.skip_reason,
                    },
                )
                continue

            projection_key = (
                projection.root.media_id,
                frozenset(projection.member_media_ids),
                projection.projection_version,
            )
            if projection_key in processed_projections:
                stats.snapshots_skipped += 1
                covered_media_ids.update(projection.member_media_ids)
                continue

            scope_stats = AnimeSeriesViewFranchiseRefreshStats()
            try:
                self._persist_projection(
                    user=user,
                    projection=projection,
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
                        "member_media_ids": list(projection.member_media_ids),
                    },
                )
                continue

            processed_projections.add(projection_key)
            covered_media_ids.update(projection.member_media_ids)
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
    def _persist_projection(
        self,
        *,
        user,
        projection,
        stats,
        dry_run,
    ):
        scope_media_ids = projection.member_media_ids
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

        for anime in tracked_anime:
            media_id = anime.item.media_id
            if projection.group_kind == GROUP_KIND_FRANCHISE:
                defaults = self._franchise_defaults(projection)
                created_field = "franchise_memberships_created"
                updated_field = "franchise_memberships_updated"
            elif projection.group_kind == GROUP_KIND_SINGLETON:
                defaults = self._singleton_defaults(projection)
                created_field = "singleton_memberships_created"
                updated_field = "singleton_memberships_updated"
            else:
                msg = (
                    f"Unsupported Anime Series View group kind: {projection.group_kind}"
                )
                raise ValueError(msg)

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
    def _franchise_defaults(projection):
        root = projection.root
        return {
            "root_media_id": root.media_id,
            "display_media_id": root.media_id,
            "display_title": root.title,
            "display_image": root.image,
            "display_media_type": root.media_type,
            "display_start_date": root.start_date,
            "group_kind": GROUP_KIND_FRANCHISE,
            "projection_version": projection.projection_version,
        }

    @staticmethod
    def _singleton_defaults(projection):
        root = projection.root
        return {
            "root_media_id": root.media_id,
            "display_media_id": root.media_id,
            "display_title": root.title,
            "display_image": root.image,
            "display_media_type": root.media_type,
            "display_start_date": root.start_date,
            "group_kind": GROUP_KIND_SINGLETON,
            "projection_version": projection.projection_version,
        }
