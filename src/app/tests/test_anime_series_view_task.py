# ruff: noqa: D102
from unittest.mock import patch

from celery.exceptions import MaxRetriesExceededError, Retry
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.anime_series_view_constants import DELETE_MODE, REFRESH_MODE
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshStats,
)
from app.services.anime_series_view_refresh_queue import (
    refresh_queue_lock_key,
    refresh_running_lock_key,
)
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
        task_cache.add.return_value = True
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
        task_cache.delete.assert_any_call(refresh_running_lock_key(user.id))
        task_cache.delete.assert_any_call(
            refresh_queue_lock_key(user.id, ["2", "10"], REFRESH_MODE)
        )

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_delete_mode_dispatches_to_delete_path(self, service_cls, task_cache):
        user = get_user_model().objects.create_user(username="series-delete-task")
        task_cache.add.return_value = True
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
        task_cache.delete.assert_any_call(refresh_running_lock_key(user.id))
        task_cache.delete.assert_any_call(
            refresh_queue_lock_key(user.id, ["20"], DELETE_MODE)
        )

    @patch("app.tasks.cache")
    def test_refresh_task_deletes_queue_lock_after_empty_ids(self, task_cache):
        empty = refresh_anime_series_view_franchise_projection(999, [])

        self.assertEqual(empty["reason"], "empty_media_ids")
        task_cache.add.assert_not_called()
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(999, [], REFRESH_MODE)
        )

    @patch("app.tasks.cache")
    def test_refresh_task_deletes_queue_lock_after_missing_user(self, task_cache):
        missing = refresh_anime_series_view_franchise_projection(999, ["2"])

        self.assertEqual(missing["reason"], "user_not_found")
        task_cache.add.assert_not_called()
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
        task_cache.add.assert_not_called()
        task_cache.delete.assert_called_once_with(
            refresh_queue_lock_key(999, ["2"], "unsupported")
        )

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_keeps_running_lock_until_service_returns(self, service_cls):
        user = get_user_model().objects.create_user(username="series-lock-task")
        running_lock_key = refresh_running_lock_key(user.id)

        def refresh_while_locked(**_kwargs):
            self.assertEqual(cache.get(running_lock_key), "1")
            return AnimeSeriesViewFranchiseRefreshStats(requested=1)

        service_cls.return_value.refresh_for_media_ids.side_effect = (
            refresh_while_locked
        )

        refresh_anime_series_view_franchise_projection(user.id, ["2"])

        self.assertIsNone(cache.get(running_lock_key))

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_releases_running_lock_after_service_exception(
        self, service_cls
    ):
        user = get_user_model().objects.create_user(username="series-error-task")
        request_lock_key = refresh_queue_lock_key(user.id, ["2"], REFRESH_MODE)
        running_lock_key = refresh_running_lock_key(user.id)
        cache.set(request_lock_key, "1", timeout=900)
        service_cls.return_value.refresh_for_media_ids.side_effect = RuntimeError(
            "boom"
        )

        with self.assertRaises(RuntimeError):
            refresh_anime_series_view_franchise_projection(user.id, ["2"])

        self.assertIsNone(cache.get(running_lock_key))
        self.assertIsNone(cache.get(request_lock_key))

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_retries_when_user_running_lock_exists(self, service_cls):
        user = get_user_model().objects.create_user(username="series-retry-task")
        running_lock_key = refresh_running_lock_key(user.id)
        cache.set(running_lock_key, "1", timeout=900)

        with (
            patch.object(
                refresh_anime_series_view_franchise_projection,
                "retry",
                side_effect=Retry("retry requested"),
            ) as retry,
            self.assertRaises(Retry),
        ):
            refresh_anime_series_view_franchise_projection(user.id, ["2"])

        retry.assert_called_once()
        service_cls.return_value.refresh_for_media_ids.assert_not_called()
        self.assertEqual(cache.get(running_lock_key), "1")

    @patch("app.tasks.logger.exception")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_retry_does_not_log_application_exception(
        self, service_cls, logger_exception
    ):
        user = get_user_model().objects.create_user(username="series-retry-log")
        running_lock_key = refresh_running_lock_key(user.id)
        cache.set(running_lock_key, "1", timeout=900)

        with (
            patch.object(
                refresh_anime_series_view_franchise_projection,
                "retry",
                side_effect=Retry("retry requested"),
            ),
            self.assertRaises(Retry),
        ):
            refresh_anime_series_view_franchise_projection(user.id, ["2"])

        logger_exception.assert_not_called()
        service_cls.return_value.refresh_for_media_ids.assert_not_called()
        self.assertEqual(cache.get(running_lock_key), "1")

    @patch("app.tasks.logger.exception")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_retries_retryable_provider_errors(
        self, service_cls, logger_exception
    ):
        user = get_user_model().objects.create_user(username="series-provider-retry")
        running_lock_key = refresh_running_lock_key(user.id)
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=1,
                errors=1,
                retryable_errors=1,
                retryable_media_ids=["20"],
            )
        )

        with (
            patch.object(
                refresh_anime_series_view_franchise_projection,
                "retry",
                side_effect=Retry("retry requested"),
            ) as retry,
            self.assertRaises(Retry),
        ):
            refresh_anime_series_view_franchise_projection(user.id, ["20"])

        retry.assert_called_once()
        self.assertEqual(
            retry.call_args.kwargs["args"], (user.id, ["20"], REFRESH_MODE)
        )
        logger_exception.assert_not_called()
        self.assertIsNone(cache.get(running_lock_key))

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_does_not_retry_non_retryable_projection_errors(
        self, service_cls
    ):
        user = get_user_model().objects.create_user(username="series-non-retry")
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=1,
                errors=1,
            )
        )

        with patch.object(
            refresh_anime_series_view_franchise_projection, "retry"
        ) as retry:
            result = refresh_anime_series_view_franchise_projection(user.id, ["20"])

        retry.assert_not_called()
        self.assertTrue(result["refreshed"])
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["retryable_errors"], 0)
        self.assertEqual(result["retryable_media_ids"], [])

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_retries_only_retryable_media_ids_after_partial_batch(
        self, service_cls
    ):
        user = get_user_model().objects.create_user(username="series-partial-retry")
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=3,
                franchise_memberships_created=2,
                errors=1,
                retryable_errors=1,
                retryable_media_ids=["20"],
            )
        )

        with (
            patch.object(
                refresh_anime_series_view_franchise_projection,
                "retry",
                side_effect=Retry("retry requested"),
            ) as retry,
            self.assertRaises(Retry),
        ):
            refresh_anime_series_view_franchise_projection(
                user.id,
                ["20", "223", "51122"],
            )

        retry.assert_called_once()
        self.assertEqual(
            retry.call_args.kwargs["args"], (user.id, ["20"], REFRESH_MODE)
        )

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_raises_when_retryable_error_exhausts_retries(
        self, service_cls
    ):
        user = get_user_model().objects.create_user(username="series-retry-exhausted")
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=1,
                errors=1,
                retryable_errors=1,
                retryable_media_ids=["20"],
            )
        )

        with (
            patch.object(
                refresh_anime_series_view_franchise_projection,
                "retry",
                side_effect=MaxRetriesExceededError("exhausted"),
            ),
            self.assertRaises(MaxRetriesExceededError),
        ):
            refresh_anime_series_view_franchise_projection(user.id, ["20"])

    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_running_lock_is_scoped_per_user(self, service_cls):
        user_a = get_user_model().objects.create_user(username="series-user-a")
        user_b = get_user_model().objects.create_user(username="series-user-b")
        cache.set(refresh_running_lock_key(user_a.id), "1", timeout=900)
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(requested=1)
        )

        refresh_anime_series_view_franchise_projection(user_b.id, ["2"])

        service_cls.return_value.refresh_for_media_ids.assert_called_once()
        self.assertEqual(cache.get(refresh_running_lock_key(user_a.id)), "1")
        self.assertIsNone(cache.get(refresh_running_lock_key(user_b.id)))
