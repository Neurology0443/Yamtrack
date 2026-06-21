# ruff: noqa: D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.anime_series_view_constants import DELETE_MODE, REFRESH_MODE
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshStats,
)
from app.services.anime_series_view_refresh_queue import refresh_queue_lock_key
from app.tasks import refresh_anime_series_view_franchise_projection


class AnimeSeriesViewTaskTests(TestCase):
    """Test task normalization, skips, service calls, and returned statistics."""

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_deletes_queue_lock_after_success(
        self,
        service_cls,
        task_cache,
    ):
        user = get_user_model().objects.create_user(username="series-task")
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=2,
                snapshots_built=1,
                franchise_memberships_created=3,
            )
        )

        result = refresh_anime_series_view_franchise_projection(
            user.id,
            ["10", "2", "2"],
        )

        service_cls.return_value.refresh_for_media_ids.assert_called_once_with(
            user=user,
            media_ids=("2", "10"),
        )
        self.assertEqual(result["media_ids"], ["2", "10"])
        self.assertEqual(result["mode"], REFRESH_MODE)
        self.assertEqual(result["franchise_memberships_created"], 3)
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(user.id, ["2", "10"], REFRESH_MODE)
        )

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_delete_mode_dispatches_to_delete_path(self, service_cls, task_cache):
        user = get_user_model().objects.create_user(username="series-delete-task")
        service_cls.return_value.refresh_after_delete.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=1,
                memberships_deleted=1,
            )
        )

        result = refresh_anime_series_view_franchise_projection(
            user.id,
            ["20"],
            DELETE_MODE,
        )

        service_cls.return_value.refresh_after_delete.assert_called_once_with(
            user=user,
            media_ids=("20",),
        )
        service_cls.return_value.refresh_for_media_ids.assert_not_called()
        self.assertEqual(result["mode"], DELETE_MODE)
        self.assertEqual(result["memberships_deleted"], 1)
        task_cache.delete.assert_called_once()

    @patch("app.tasks.cache")
    def test_refresh_task_deletes_queue_lock_after_empty_ids(self, task_cache):
        empty = refresh_anime_series_view_franchise_projection(999, [])

        self.assertEqual(empty["reason"], "empty_media_ids")
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(999, [], REFRESH_MODE)
        )

    @patch("app.tasks.cache")
    def test_refresh_task_deletes_queue_lock_after_missing_user(self, task_cache):
        missing = refresh_anime_series_view_franchise_projection(999, ["2"])

        self.assertEqual(missing["reason"], "user_not_found")
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(999, ["2"], REFRESH_MODE)
        )

    @patch("app.tasks.cache")
    def test_refresh_task_skips_invalid_mode(self, task_cache):
        result = refresh_anime_series_view_franchise_projection(
            999,
            ["2"],
            "unsupported",
        )

        self.assertEqual(result["reason"], "invalid_mode")
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(999, ["2"], "unsupported")
        )

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_keeps_lock_until_service_returns(self, service_cls):
        user = get_user_model().objects.create_user(username="series-lock-task")
        lock_key = refresh_queue_lock_key(user.id, ["2"], REFRESH_MODE)
        cache.set(lock_key, "1", timeout=900)

        def refresh_while_locked(**_kwargs):
            self.assertEqual(cache.get(lock_key), "1")
            return AnimeSeriesViewFranchiseRefreshStats(requested=1)

        service_cls.return_value.refresh_for_media_ids.side_effect = (
            refresh_while_locked
        )

        refresh_anime_series_view_franchise_projection(user.id, ["2"])

        self.assertIsNone(cache.get(lock_key))
