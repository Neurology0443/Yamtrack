"""Scoped persistence for resolved local anime series memberships."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from app.models import AnimeLocalSeriesMembership
from app.services.anime_tracking import bulk_mal_anime_tracked_ids

SERIES_VIEW_PROFILE_KEY = "series_view"


@dataclass(frozen=True)
class AnimeLocalSeriesProjectionStats:
    """Persistence counters for one canonical scope."""

    memberships_recorded: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_deleted: int = 0


class AnimeLocalSeriesProjectionService:
    """Persist a resolver result without deciding any grouping semantics."""

    @transaction.atomic
    def persist(
        self,
        *,
        user,
        source_profile_key,
        resolver_version,
        resolution,
        scope_media_ids,
    ):
        """Replace memberships only inside the explicitly supplied scope."""
        profile_key = str(source_profile_key).strip()
        version = str(resolver_version).strip()
        if not profile_key or not version:
            message = "source_profile_key and resolver_version are required"
            raise ValueError(message)

        scope = {
            str(media_id).strip()
            for media_id in scope_media_ids
            if media_id is not None and str(media_id).strip()
        }
        resolved_ids = {
            str(media_id)
            for group in resolution.groups
            for media_id in group.member_media_ids
        }
        if not resolved_ids <= scope:
            message = "resolution contains media outside projection scope"
            raise ValueError(message)

        tracked_ids = bulk_mal_anime_tracked_ids(
            user_id=user.id,
            media_ids=scope,
        )
        existing = AnimeLocalSeriesMembership.objects.filter(
            user=user,
            source_profile_key=profile_key,
            media_id__in=scope,
        )
        deleted_old_versions, _ = existing.exclude(
            resolver_version=version
        ).delete()

        created = 0
        updated = 0
        retained_ids = set()
        for group in resolution.groups:
            member_ids = [
                str(media_id)
                for media_id in group.member_media_ids
                if str(media_id) in tracked_ids
            ]
            if not member_ids:
                continue
            for media_id in member_ids:
                _, was_created = AnimeLocalSeriesMembership.objects.update_or_create(
                    user=user,
                    media_id=media_id,
                    source_profile_key=profile_key,
                    resolver_version=version,
                    defaults={
                        "root_media_id": str(group.root_media_id),
                        "group_kind": str(group.group_kind),
                        "context_parent_media_id": (
                            str(group.context_parent_media_id)
                            if group.context_parent_media_id
                            else ""
                        ),
                        "context_relation_type": (
                            str(group.context_relation_type)
                            if group.context_relation_type
                            else ""
                        ),
                        "component_size": len(member_ids),
                    },
                )
                retained_ids.add(media_id)
                created += int(was_created)
                updated += int(not was_created)

        deleted_stale, _ = existing.filter(resolver_version=version).exclude(
            media_id__in=retained_ids
        ).delete()
        return AnimeLocalSeriesProjectionStats(
            memberships_recorded=len(retained_ids),
            memberships_created=created,
            memberships_updated=updated,
            memberships_deleted=deleted_old_versions + deleted_stale,
        )
