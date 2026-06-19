"""Persistence for resolved local anime series memberships."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from app.models import AnimeLocalSeriesMembership
from app.services.anime_tracking import bulk_mal_anime_tracked_ids


@dataclass(frozen=True)
class AnimeLocalSeriesProjectionStats:
    """Counters produced while persisting one local-series resolution."""

    memberships_recorded: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_deleted: int = 0


class AnimeLocalSeriesProjectionService:
    """Persist resolver output without making grouping decisions."""

    @transaction.atomic
    def persist(
        self,
        *,
        user,
        resolution,
        source_profile_key: str,
        scope_media_ids,
    ) -> AnimeLocalSeriesProjectionStats:
        """Upsert memberships that still correspond to tracked MAL anime."""
        source_profile_key = str(source_profile_key).strip()
        if not source_profile_key:
            message = "source_profile_key is required"
            raise ValueError(message)

        resolver_version = str(resolution.resolver_version).strip()
        if not resolver_version:
            message = "resolver_version is required"
            raise ValueError(message)

        normalized_scope_media_ids = {
            str(media_id).strip()
            for media_id in scope_media_ids
            if media_id is not None and str(media_id).strip()
        }
        resolved_media_ids = {
            str(media_id)
            for group in resolution.groups
            for media_id in group.member_media_ids
        }
        if not resolved_media_ids.issubset(normalized_scope_media_ids):
            message = "resolution contains media outside projection scope"
            raise ValueError(message)

        tracked_media_ids = bulk_mal_anime_tracked_ids(
            user_id=user.id,
            media_ids=resolved_media_ids,
        )

        scoped_memberships = AnimeLocalSeriesMembership.objects.filter(
            user=user,
            source_profile_key=source_profile_key,
            media_id__in=normalized_scope_media_ids,
        )
        deleted_old_versions, _ = scoped_memberships.exclude(
            resolver_version=resolver_version,
        ).delete()

        created_count = 0
        updated_count = 0
        retained_media_ids = set()
        for group in resolution.groups:
            member_ids = [
                str(media_id)
                for media_id in group.member_media_ids
                if str(media_id) in tracked_media_ids
            ]
            if not member_ids:
                continue

            component_size = len(member_ids)
            for media_id in member_ids:
                _membership, created = (
                    AnimeLocalSeriesMembership.objects.update_or_create(
                        user=user,
                        media_id=media_id,
                        source_profile_key=source_profile_key,
                        resolver_version=resolver_version,
                        defaults={
                            "root_media_id": str(group.root_media_id),
                            "group_kind": group.group_kind,
                            "context_parent_media_id": (
                                str(group.context_parent_media_id)
                                if group.context_parent_media_id is not None
                                else ""
                            ),
                            "context_relation_type": (
                                str(group.context_relation_type)
                                if group.context_relation_type is not None
                                else ""
                            ),
                            "component_size": component_size,
                        },
                    )
                )
                retained_media_ids.add(media_id)
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        stale_memberships = scoped_memberships.filter(
            resolver_version=resolver_version,
        ).exclude(media_id__in=retained_media_ids)
        deleted_stale, _ = stale_memberships.delete()
        return AnimeLocalSeriesProjectionStats(
            memberships_recorded=len(retained_media_ids),
            memberships_created=created_count,
            memberships_updated=updated_count,
            memberships_deleted=deleted_old_versions + deleted_stale,
        )
