"""Explicit transaction-safe triggers for Anime Series View refreshes."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

from app.services.anime_series_view_refresh_queue import (
    get_refresh_queue_lock_timeout_seconds,
    normalize_media_ids,
    refresh_queue_lock_key,
)

logger = logging.getLogger(__name__)


class AnimeSeriesViewRefreshTriggerService:
    """Register collection refreshes at coherent transaction boundaries."""

    def schedule_manual_add(self, *, user, media_id) -> None:
        """Refresh after one manually tracked MAL anime commits."""
        self._schedule(user=user, media_ids={str(media_id)})

    def schedule_delete(self, *, user, media_id) -> None:
        """Refresh after one tracked MAL anime deletion commits."""
        self._schedule(user=user, media_ids={str(media_id)})

    def schedule_import_batch(
        self,
        *,
        user,
        seed_media_id,
        component_root_media_id=None,
    ) -> None:
        """Refresh once after a successful import seed batch commits."""
        media_ids = {str(seed_media_id)}
        if component_root_media_id:
            media_ids.add(str(component_root_media_id))
        self._schedule(user=user, media_ids=media_ids)

    @staticmethod
    def _schedule(*, user, media_ids) -> None:
        normalized_ids = normalize_media_ids(media_ids)
        if not normalized_ids:
            return
        user_id = user.id

        def enqueue_refresh():
            from app.tasks import (  # noqa: PLC0415
                refresh_anime_series_view_projection,
            )

            lock_key = refresh_queue_lock_key(user_id, normalized_ids)
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
                refresh_anime_series_view_projection.delay(
                    user_id,
                    list(normalized_ids),
                )
                logger.info(
                    "Anime Series View refresh queued",
                    extra={
                        "user_id": user_id,
                        "media_ids": list(normalized_ids),
                    },
                )
            except Exception:
                cache.delete(lock_key)
                logger.exception(
                    "Failed to enqueue Anime Series View refresh",
                    extra={
                        "user_id": user_id,
                        "media_ids": list(normalized_ids),
                    },
                )

        transaction.on_commit(enqueue_refresh)
