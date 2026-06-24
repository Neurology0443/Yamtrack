"""Post-commit triggers for coordinated manual MAL anime franchise work."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

from app.services.anime_franchise_cache import get_queue_lock_ttl_seconds

logger = logging.getLogger(__name__)


def manual_add_queue_lock_key(user_id, media_id):
    """Return the queue lock key for a manual add franchise task."""
    return f"anime_franchise_manual_add:{user_id}:{media_id}"


class AnimeFranchiseManualAddTriggerService:
    """Schedule coordinated franchise projections after manual MAL anime creation."""

    def schedule_manual_add(self, *, user, media_id) -> None:
        """Schedule the coordinated post-add task after transaction commit."""
        media_id = str(media_id)
        user_id = user.id

        def enqueue_manual_add():
            from app.tasks import process_manual_mal_anime_franchise  # noqa: PLC0415

            lock_key = manual_add_queue_lock_key(user_id, media_id)
            acquired = cache.add(
                lock_key,
                "1",
                timeout=get_queue_lock_ttl_seconds(),
            )
            if not acquired:
                logger.info(
                    "Manual MAL anime franchise task already queued",
                    extra={"user_id": user_id, "media_id": media_id},
                )
                return

            try:
                process_manual_mal_anime_franchise.delay(user_id, media_id)
            except Exception:
                cache.delete(lock_key)
                logger.exception(
                    "Failed to enqueue manual MAL anime franchise task",
                    extra={"user_id": user_id, "media_id": media_id},
                )

        transaction.on_commit(enqueue_manual_add)
