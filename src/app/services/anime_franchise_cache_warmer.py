"""Schedule forced MAL anime franchise cache warm builds."""

from __future__ import annotations

import logging

from celery import current_app
from django.core.cache import cache
from django.db import transaction

from app.services import anime_franchise_cache

logger = logging.getLogger(__name__)

MAL_ANIME_FRANCHISE_BUILD_TASK_NAME = "Build MAL anime franchise payload"


def schedule_mal_anime_franchise_cache_warm(root_media_id: str) -> bool:
    """Schedule a forced MAL anime franchise cache warm build after commit.

    This intentionally bypasses freshness checks because a real import creation
    means the user library changed and the canonical franchise payload should be
    rebuilt even if the previous payload is still logically fresh.

    The function does not import app.tasks to avoid circular imports.
    """
    root_media_id = str(root_media_id)
    scheduled = False

    def enqueue() -> None:
        nonlocal scheduled

        queue_lock_key = anime_franchise_cache.get_queue_lock_key(root_media_id)
        acquired = cache.add(
            queue_lock_key,
            "1",
            timeout=anime_franchise_cache.get_queue_lock_ttl_seconds(),
        )
        if not acquired:
            logger.info(
                "MAL anime franchise cache warm build already queued "
                "for component_root_mal_id=%s",
                root_media_id,
            )
            return

        try:
            current_app.send_task(
                MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
                args=[root_media_id],
            )
        except Exception:
            cache.delete(queue_lock_key)
            logger.exception(
                "Failed to schedule MAL anime franchise cache warm build "
                "for component_root_mal_id=%s",
                root_media_id,
            )
            return

        scheduled = True
        logger.info(
            "Scheduled MAL anime franchise cache warm build "
            "for component_root_mal_id=%s",
            root_media_id,
        )

    transaction.on_commit(enqueue)
    return scheduled
