# ruff: noqa: D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.services.anime_series_view_refresh_queue import refresh_queue_lock_key
from app.services.anime_series_view_refresh_triggers import (
    AnimeSeriesViewRefreshTriggerService,
)


class AnimeSeriesViewRefreshTriggerTests(TestCase):
    """Test commit timing, normalization, lock de-duplication, and failures."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="series-trigger")

    @patch("app.tasks.refresh_anime_series_view_franchise_projection.delay")
    def test_import_batch_enqueues_once_after_commit_with_normalized_ids(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            AnimeSeriesViewRefreshTriggerService().schedule_import_batch(
                user=self.user,
                media_ids=["10", "2", "2"],
            )
            delay.assert_not_called()

        delay.assert_called_once_with(self.user.id, ["2", "10"])

    @patch("app.tasks.refresh_anime_series_view_franchise_projection.delay")
    def test_queue_lock_prevents_duplicate_enqueue(self, delay):
        service = AnimeSeriesViewRefreshTriggerService()
        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_manual_add(user=self.user, media_id="2")
        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_delete(user=self.user, media_id="2")

        delay.assert_called_once()

    @patch(
        "app.tasks.refresh_anime_series_view_franchise_projection.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_enqueue_failure_releases_queue_lock(self, _delay):
        with self.captureOnCommitCallbacks(execute=True):
            AnimeSeriesViewRefreshTriggerService().schedule_manual_add(
                user=self.user,
                media_id="2",
            )

        self.assertIsNone(cache.get(refresh_queue_lock_key(self.user.id, ["2"])))
