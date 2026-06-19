"""Persist stable per-user anime continuity component memberships."""

from collections.abc import Iterable

from django.db import transaction
from django.utils import timezone

from app.models import (
    Anime,
    AnimeImportComponentMembership,
    MediaTypes,
    Sources,
)


class AnimeImportComponentMembershipService:
    """Synchronize tracked anime memberships without affecting scan scheduling."""

    @transaction.atomic
    def record_tracked_component(
        self,
        *,
        user_id: int,
        media_ids: Iterable[str],
        component_root_mal_id: str,
        component_size: int,
        source_profile_key: str,
    ) -> int:
        """Upsert the component root for every tracked member in the snapshot."""
        component_root_mal_id = str(component_root_mal_id).strip()
        if not component_root_mal_id:
            msg = "component_root_mal_id must not be empty"
            raise ValueError(msg)

        normalized_media_ids = {
            str(media_id)
            for media_id in media_ids
            if media_id not in (None, "")
        }
        if not normalized_media_ids:
            return 0

        tracked_media_ids = set(
            Anime.objects.filter(
                user_id=user_id,
                item__media_id__in=normalized_media_ids,
                item__source=Sources.MAL.value,
                item__media_type=MediaTypes.ANIME.value,
            )
            .values_list("item__media_id", flat=True)
            .distinct(),
        )
        if not tracked_media_ids:
            return 0

        memberships = AnimeImportComponentMembership.objects.filter(
            user_id=user_id,
            media_id__in=tracked_media_ids,
        )
        existing_media_ids = set(
            memberships.values_list("media_id", flat=True),
        )
        now = timezone.now()
        memberships.update(
            component_root_mal_id=component_root_mal_id,
            component_size=component_size,
            source_profile_key=source_profile_key,
            updated_at=now,
        )
        AnimeImportComponentMembership.objects.bulk_create(
            [
                AnimeImportComponentMembership(
                    user_id=user_id,
                    media_id=media_id,
                    component_root_mal_id=component_root_mal_id,
                    component_size=component_size,
                    source_profile_key=source_profile_key,
                )
                for media_id in sorted(tracked_media_ids - existing_media_ids)
            ],
        )
        return len(tracked_media_ids)
