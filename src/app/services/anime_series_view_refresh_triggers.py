"""Non-blocking web/import triggers for Anime Series View projection refreshes."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

from app.anime_series_view_constants import DELETE_MODE, REFRESH_MODE
from app.services.anime_series_view_refresh_queue import (
    get_refresh_queue_lock_timeout_seconds,
    normalize_media_ids,
    refresh_queue_lock_key,
)

logger = logging.getLogger(__name__)


class AnimeSeriesViewRefreshTriggerService:
    """Schedule projection refreshes only after the surrounding commit succeeds."""

    def schedule_manual_add(self, *, user, media_id) -> None:
        """Schedule a refresh after a manual MAL anime creation."""
        self._schedule(user=user, media_ids=(media_id,), mode=REFRESH_MODE)

    def schedule_delete(self, *, user, media_id) -> None:
        """Schedule cleanup and regrouping after a MAL anime deletion."""
        self._schedule(user=user, media_ids=(media_id,), mode=DELETE_MODE)

    def schedule_import_batch(self, *, user, media_ids) -> None:
        """Schedule one normalized refresh batch for an import snapshot."""
        self._schedule(user=user, media_ids=media_ids, mode=REFRESH_MODE)

    def _schedule(self, *, user, media_ids, mode) -> None:
        normalized_ids = normalize_media_ids(media_ids)
        if not normalized_ids:
            return

        user_id = user.id

        def enqueue_refresh():
            from app.tasks import (  # noqa: PLC0415
                refresh_anime_series_view_franchise_projection,
            )

            lock_key = refresh_queue_lock_key(user_id, normalized_ids, mode)
            acquired = cache.add(
                lock_key,
                "1",
                timeout=get_refresh_queue_lock_timeout_seconds(),
            )
            if not acquired:
                logger.info(
                    "Anime Series View refresh already queued",
                    extra={
                        "user_id": user_id,
                        "media_ids": list(normalized_ids),
                    },
                )
                return

            try:
                refresh_anime_series_view_franchise_projection.delay(
                    user_id,
                    list(normalized_ids),
                    mode,
                )
            except Exception:
                cache.delete(lock_key)
                logger.exception(
                    "Failed to enqueue Anime Series View refresh",
                    extra={
                        "user_id": user_id,
                        "media_ids": list(normalized_ids),
                        "mode": mode,
                    },
                )

        transaction.on_commit(enqueue_refresh)
