"""Queue helpers for asynchronous Anime Series View refreshes."""

from __future__ import annotations

import hashlib

from django.conf import settings

QUEUE_LOCK_PREFIX = "anime_series_view_refresh_queue_lock"
DEFAULT_QUEUE_LOCK_SECONDS = 120


def media_id_key(media_id):
    """Sort numeric MAL IDs numerically before non-numeric identifiers."""
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)


def normalize_media_ids(media_ids):
    """Return unique, non-empty media IDs in deterministic order."""
    if media_ids is None:
        return ()
    if isinstance(media_ids, str):
        media_ids = (media_ids,)

    return tuple(
        sorted(
            {
                str(media_id).strip()
                for media_id in media_ids
                if media_id is not None and str(media_id).strip()
            },
            key=media_id_key,
        )
    )


def refresh_queue_lock_key(user_id, media_ids):
    """Build a deterministic short-lived queue lock key."""
    joined = ",".join(normalize_media_ids(media_ids))
    digest = hashlib.sha1(
        joined.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:16]
    return f"{QUEUE_LOCK_PREFIX}:{user_id}:{digest}"


def get_refresh_queue_lock_timeout_seconds():
    """Return the configured short queue lock lifetime."""
    return getattr(
        settings,
        "ANIME_SERIES_VIEW_REFRESH_QUEUE_LOCK_SECONDS",
        DEFAULT_QUEUE_LOCK_SECONDS,
    )
