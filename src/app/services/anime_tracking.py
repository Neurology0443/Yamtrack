"""Helpers for checking user-tracked MAL anime entries."""

from __future__ import annotations

from app.models import Anime, MediaTypes, Sources


def is_mal_anime_tracked(*, user_id, media_id) -> bool:
    """Return whether one MAL anime media ID is already tracked by a user."""
    return Anime.objects.filter(
        user_id=user_id,
        item__media_id=str(media_id),
        item__source=Sources.MAL.value,
        item__media_type=MediaTypes.ANIME.value,
    ).exists()


def bulk_mal_anime_tracked_ids(*, user_id, media_ids) -> set[str]:
    """Return the subset of MAL anime media IDs tracked by a user."""
    normalized_ids = {
        str(media_id).strip()
        for media_id in media_ids
        if media_id is not None and str(media_id).strip()
    }
    if not normalized_ids:
        return set()

    return {
        str(media_id)
        for media_id in Anime.objects.filter(
            user_id=user_id,
            item__media_id__in=normalized_ids,
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
        ).values_list("item__media_id", flat=True)
    }
