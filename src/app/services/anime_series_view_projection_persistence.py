"""Scoped persistence for the Anime Series View read model."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from app.models import AnimeSeriesViewMembership

SERIES_VIEW_PROFILE_KEY = "series_view"


@dataclass(frozen=True)
class AnimeSeriesViewPersistenceStats:
    """Counters produced while replacing one projection scope."""

    memberships_recorded: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_deleted: int = 0


class AnimeSeriesViewProjectionPersistenceService:
    """Persist projections without making grouping decisions."""

    @transaction.atomic
    def persist(
        self,
        *,
        user,
        projection,
        scope_media_ids,
        source_profile_key=SERIES_VIEW_PROFILE_KEY,
        dry_run=False,
    ) -> AnimeSeriesViewPersistenceStats:
        """Replace memberships only within the supplied snapshot scope."""
        scope = {
            str(media_id).strip()
            for media_id in scope_media_ids
            if media_id is not None and str(media_id).strip()
        }
        projected_ids = {
            str(media_id)
            for group in projection.groups
            for media_id in group.member_media_ids
        }
        if not projected_ids <= scope:
            message = "projection contains media outside snapshot scope"
            raise ValueError(message)

        if dry_run:
            return AnimeSeriesViewPersistenceStats(
                memberships_recorded=len(projected_ids),
            )

        existing = AnimeSeriesViewMembership.objects.filter(
            user=user,
            source_profile_key=source_profile_key,
            media_id__in=scope,
        )
        deleted_old_versions, _ = existing.exclude(
            projection_version=projection.projection_version,
        ).delete()

        created = 0
        updated = 0
        retained_ids = set()
        for group in projection.groups:
            component_size = len(group.member_media_ids)
            for raw_media_id in group.member_media_ids:
                media_id = str(raw_media_id)
                _, was_created = AnimeSeriesViewMembership.objects.update_or_create(
                    user=user,
                    media_id=media_id,
                    source_profile_key=source_profile_key,
                    projection_version=projection.projection_version,
                    defaults={
                        "root_media_id": str(group.root_media_id),
                        "display_media_id": str(group.display_media_id),
                        "group_kind": str(group.group_kind),
                        "context_parent_media_id": (
                            str(group.context_parent_media_id)
                            if group.context_parent_media_id
                            else None
                        ),
                        "context_relation_type": (
                            str(group.context_relation_type)
                            if group.context_relation_type
                            else None
                        ),
                        "component_size": component_size,
                    },
                )
                retained_ids.add(media_id)
                created += int(was_created)
                updated += int(not was_created)

        deleted_stale, _ = existing.filter(
            projection_version=projection.projection_version,
        ).exclude(media_id__in=retained_ids).delete()
        return AnimeSeriesViewPersistenceStats(
            memberships_recorded=len(retained_ids),
            memberships_created=created,
            memberships_updated=updated,
            memberships_deleted=deleted_old_versions + deleted_stale,
        )
