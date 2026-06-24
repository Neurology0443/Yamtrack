# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.tasks import process_manual_mal_anime_franchise


class ProcessManualMALAnimeFranchiseTaskTests(TestCase):
    @patch("app.tasks.cache.delete")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    @patch("app.tasks.AnimeSeriesViewProjectionBuilder")
    @patch("app.tasks.AnimeFranchiseCacheBuildService")
    @patch("app.tasks.AnimeFranchiseBuildSession")
    def test_task_uses_one_build_session_for_cache_and_series_view(
        self,
        build_session_class,
        cache_service_class,
        projection_builder_class,
        refresh_service_class,
        _cache_delete,
    ):
        user = get_user_model().objects.create_user(username="manual")
        build_session = Mock()
        snapshot_service = Mock()
        build_session.build_series_view_snapshot_service.return_value = snapshot_service
        build_session_class.return_value = build_session
        cache_service_class.return_value.build_and_save.return_value = {
            "built": True,
            "canonical_media_id": "100",
        }
        stats = SimpleNamespace(
            requested=1,
            snapshots_built=1,
            snapshots_skipped=0,
            franchise_memberships_created=1,
            franchise_memberships_updated=0,
            singleton_memberships_created=0,
            singleton_memberships_updated=0,
            memberships_deleted=0,
            errors=0,
        )
        refresh_service_class.return_value.refresh_for_media_ids.return_value = stats

        result = process_manual_mal_anime_franchise(user.id, 100)

        cache_service_class.assert_called_once_with(build_session=build_session)
        cache_service_class.return_value.build_and_save.assert_called_once_with(
            "100",
            refresh_cache=False,
            force_cache_rebuild=True,
        )
        projection_builder_class.assert_called_once_with(
            snapshot_service=snapshot_service,
        )
        refresh_service_class.assert_called_once_with(
            projection_builder=projection_builder_class.return_value,
        )
        refresh_service_class.return_value.refresh_for_media_ids.assert_called_once_with(
            user=user,
            media_ids=("100",),
            refresh_cache=False,
        )
        self.assertTrue(result["cache_ui"]["success"])
        self.assertTrue(result["series_view"]["success"])


    @patch("app.tasks.cache.delete")
    @patch("app.tasks.get_user_model")
    def test_task_deletes_manual_lock_on_unexpected_error(
        self,
        get_user_model_mock,
        cache_delete,
    ):
        get_user_model_mock.side_effect = RuntimeError("database unavailable")

        with self.assertRaises(RuntimeError):
            process_manual_mal_anime_franchise(7, 100)

        cache_delete.assert_called_once_with("anime_franchise_manual_add:7:100")
