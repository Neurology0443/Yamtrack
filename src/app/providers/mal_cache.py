"""Cache helpers for MyAnimeList anime detail metadata."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import MediaTypes, Sources

logger = logging.getLogger(__name__)


def get_anime_cache_key(media_id) -> str:
    """Return the payload cache key for MAL anime detail metadata."""
    return f"{Sources.MAL.value}_{MediaTypes.ANIME.value}_{media_id}"


def get_anime_cache_meta_key(media_id) -> str:
    """Return the metadata cache key for MAL anime detail metadata."""
    return f"{get_anime_cache_key(media_id)}:meta"


def get_anime_refresh_lock_key(media_id) -> str:
    """Return the enqueue lock key for MAL anime stale refreshes."""
    return f"mal_anime_refresh_lock:{media_id}"


def get_anime_refresh_task_lock_key(media_id) -> str:
    """Return the execution lock key for MAL anime refresh tasks."""
    return f"mal_anime_refresh_task_lock:{media_id}"


def get_keep_ttl_seconds() -> int:
    """Return the long-lived sliding TTL for MAL anime detail cache entries."""
    return settings.MAL_CACHE_KEEP_DAYS * 24 * 60 * 60


def get_refresh_lock_ttl_seconds() -> int:
    """Return the lock TTL used to throttle queued stale refreshes."""
    return settings.MAL_CACHE_REFRESH_MIN_INTERVAL_HOURS * 60 * 60


def get_fresh_cutoff():
    """Return the oldest fetched_at timestamp still considered fresh."""
    return timezone.now() - timedelta(days=settings.MAL_CACHE_FRESH_DAYS)


def _serialize_datetime(value):
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _parse_datetime(value):
    if value in (None, ""):
        return None
    if hasattr(value, "tzinfo"):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = parse_datetime(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _default_meta(*, fetched_at=None, last_accessed_at=None):
    now = timezone.now()
    return {
        "fetched_at": _serialize_datetime(fetched_at or now),
        "last_accessed_at": _serialize_datetime(last_accessed_at or now),
        "last_refresh_attempt_at": None,
        "last_refresh_error_at": None,
        "last_error_message": "",
    }


def _normalize_meta(meta):
    normalized = {
        "fetched_at": None,
        "last_accessed_at": timezone.now().isoformat(),
        "last_refresh_attempt_at": None,
        "last_refresh_error_at": None,
        "last_error_message": "",
    }
    if isinstance(meta, dict):
        normalized.update({key: meta.get(key) for key in normalized})
    if normalized["last_error_message"] is None:
        normalized["last_error_message"] = ""
    return normalized


def load_anime_cache(media_id):
    """Load MAL anime payload and sidecar metadata from cache.

    Existing payload-only entries are upgraded lazily and given the long sliding TTL.
    """
    payload = cache.get(get_anime_cache_key(media_id))
    if payload is None:
        return None, None

    meta = cache.get(get_anime_cache_meta_key(media_id))
    if meta is None:
        meta = _default_meta()
        ttl = get_keep_ttl_seconds()
        _touch_or_set(get_anime_cache_key(media_id), payload, ttl)
        cache.set(
            get_anime_cache_meta_key(media_id),
            meta,
            timeout=ttl,
        )
        return payload, meta

    return payload, _normalize_meta(meta)


def save_anime_cache(media_id, payload, *, fetched_at=None):
    """Save MAL anime detail payload and fresh sidecar metadata."""
    meta = _default_meta(fetched_at=fetched_at)
    ttl = get_keep_ttl_seconds()
    cache.set(get_anime_cache_key(media_id), payload, timeout=ttl)
    cache.set(get_anime_cache_meta_key(media_id), meta, timeout=ttl)
    return meta


def _touch_or_set(key, value, ttl):
    try:
        if cache.touch(key, timeout=ttl):
            return
    except (AttributeError, NotImplementedError, TypeError):
        pass

    if value is None:
        value = cache.get(key)
    if value is not None:
        cache.set(key, value, timeout=ttl)


def touch_anime_cache(media_id, payload=None, meta=None):
    """Extend MAL anime cache TTLs and update the last_accessed_at timestamp."""
    ttl = get_keep_ttl_seconds()
    if payload is None:
        payload = cache.get(get_anime_cache_key(media_id))
    if payload is None:
        return _normalize_meta(meta)
    if meta is None:
        meta = cache.get(get_anime_cache_meta_key(media_id))
    meta = _normalize_meta(meta)
    meta["last_accessed_at"] = timezone.now().isoformat()

    _touch_or_set(get_anime_cache_key(media_id), payload, ttl)
    cache.set(get_anime_cache_meta_key(media_id), meta, timeout=ttl)
    return meta


def is_cache_fresh(meta) -> bool:
    """Return whether a MAL anime cache metadata record is fresh."""
    if not meta or not meta.get("fetched_at"):
        return False
    fetched_at = _parse_datetime(meta["fetched_at"])
    if fetched_at is None:
        return False
    return fetched_at >= get_fresh_cutoff()


def _is_within_cooldown(value, hours) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return False
    return parsed > timezone.now() - timedelta(hours=hours)


def can_schedule_refresh(meta) -> bool:
    """Return whether stale cache metadata is outside refresh/error cooldowns."""
    if not meta:
        return False
    if is_cache_fresh(meta):
        return False
    if _is_within_cooldown(
        meta.get("last_refresh_attempt_at"),
        settings.MAL_CACHE_REFRESH_MIN_INTERVAL_HOURS,
    ):
        return False
    return not _is_within_cooldown(
        meta.get("last_refresh_error_at"),
        settings.MAL_CACHE_RETRY_AFTER_ERROR_HOURS,
    )


def _update_meta(media_id, updates):
    payload = cache.get(get_anime_cache_key(media_id))
    if payload is None:
        return None

    ttl = get_keep_ttl_seconds()
    meta = _normalize_meta(cache.get(get_anime_cache_meta_key(media_id)))
    meta.update(updates)
    cache.set(get_anime_cache_meta_key(media_id), meta, timeout=ttl)
    _touch_or_set(get_anime_cache_key(media_id), payload, ttl)
    return meta


def mark_refresh_attempt(media_id):
    """Record that a MAL anime refresh was attempted."""
    return _update_meta(
        media_id,
        {"last_refresh_attempt_at": timezone.now().isoformat()},
    )


def mark_refresh_error(media_id, error_message):
    """Record a concise MAL anime refresh error while preserving cached payload."""
    return _update_meta(
        media_id,
        {
            "last_refresh_error_at": timezone.now().isoformat(),
            "last_error_message": str(error_message)[:250],
        },
    )


def maybe_schedule_refresh(media_id, meta=None) -> bool:
    """Queue a background MAL anime metadata refresh if cooldowns permit."""
    payload = cache.get(get_anime_cache_key(media_id))
    if payload is None:
        return False
    if meta is None:
        meta = cache.get(get_anime_cache_meta_key(media_id))
    meta = _normalize_meta(meta)
    if not can_schedule_refresh(meta):
        return False

    lock_key = get_anime_refresh_lock_key(media_id)
    if not cache.add(lock_key, "1", timeout=get_refresh_lock_ttl_seconds()):
        return False

    try:
        from app.tasks import refresh_mal_anime_metadata  # noqa: PLC0415

        refresh_mal_anime_metadata.delay(media_id)
        mark_refresh_attempt(media_id)
    except Exception:
        cache.delete(lock_key)
        logger.exception(
            "Failed to enqueue MAL anime metadata refresh for %s",
            media_id,
        )
        return False

    return True
