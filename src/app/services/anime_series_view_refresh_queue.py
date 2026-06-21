"""Queue de-duplication helpers for Anime Series View refreshes."""

from __future__ import annotations

import hashlib

from django.conf import settings

QUEUE_LOCK_PREFIX = "anime_series_view_refresh_queue_lock"
DEFAULT_QUEUE_LOCK_SECONDS = 900
RUNNING_LOCK_PREFIX = "anime_series_view_refresh_running_lock"
DEFAULT_RUNNING_LOCK_SECONDS = 900
DEFAULT_RUNNING_LOCK_RETRY_SECONDS = 30


def media_id_key(media_id):
    """Sort numeric MAL IDs naturally while remaining robust to arbitrary IDs."""
    media_id = str(media_id)
    try:
        return (0, int(media_id))
    except ValueError:
        return (1, media_id)


def normalize_media_ids(media_ids):
    """Return stable, de-duplicated media IDs without iterating strings as lists."""
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


def refresh_queue_lock_key(user_id, media_ids, mode="refresh"):
    """Build a short, order-independent cache lock key."""
    normalized_ids = normalize_media_ids(media_ids)
    payload = f"{mode}:{','.join(normalized_ids)}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:20]
    return f"{QUEUE_LOCK_PREFIX}:{user_id}:{digest}"


def get_refresh_queue_lock_timeout_seconds():
    """Return the configured timeout covering normal queue and execution time."""
    return getattr(
        settings,
        "ANIME_SERIES_VIEW_REFRESH_QUEUE_LOCK_SECONDS",
        DEFAULT_QUEUE_LOCK_SECONDS,
    )


# V1 conservative lock: serialize all Anime Series View refreshes for one user.
# Spec V2 should replace this with a finer user + global franchise root lock once
# the global franchise index can resolve refresh scopes before persistence.
def refresh_running_lock_key(user_id):
    """Build the user-scoped running lock key for refresh execution."""
    return f"{RUNNING_LOCK_PREFIX}:{user_id}"


def get_refresh_running_lock_timeout_seconds():
    """Return the configured timeout for an in-flight user refresh."""
    return getattr(
        settings,
        "ANIME_SERIES_VIEW_REFRESH_RUNNING_LOCK_SECONDS",
        DEFAULT_RUNNING_LOCK_SECONDS,
    )


def get_refresh_running_lock_retry_seconds():
    """Return the retry delay when a user refresh is already running."""
    return getattr(
        settings,
        "ANIME_SERIES_VIEW_REFRESH_RUNNING_LOCK_RETRY_SECONDS",
        DEFAULT_RUNNING_LOCK_RETRY_SECONDS,
    )
