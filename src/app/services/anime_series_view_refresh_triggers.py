"""Explicit transaction-safe triggers for Anime Series View refreshes."""

from __future__ import annotations

from django.db import transaction

from app.services.anime_series_view_projection_refresh import (
    refresh_anime_series_view_best_effort,
)


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
        affected_ids = frozenset(str(media_id) for media_id in media_ids)

        def refresh():
            refresh_anime_series_view_best_effort(
                user=user,
                media_ids=affected_ids,
            )

        transaction.on_commit(refresh)
