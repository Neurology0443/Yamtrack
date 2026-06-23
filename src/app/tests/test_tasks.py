# ruff: noqa: D101,D102
from datetime import timedelta
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import UserMessage, UserMessageLevel
from app.providers import mal_cache
from app.services import anime_franchise_cache
from app.services.anime_franchise_import import FranchiseImportStats
from app.services.anime_franchise_task_names import (
    MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
)
from app.tasks import (
    build_mal_anime_franchise_payload,
    cleanup_user_messages,
    import_anime_franchise,
    refresh_mal_anime_metadata,
)

MAL_API_RESPONSE = {
    "id": 1,
    "title": "Fresh Anime",
    "media_type": "tv",
    "main_picture": {"large": "http://example.com/anime.jpg"},
    "synopsis": "Synopsis",
    "status": "finished_airing",
    "genres": [{"name": "Action"}],
    "mean": 8.1,
    "num_scoring_users": 100,
    "num_episodes": 12,
    "average_episode_duration": 1440,
    "studios": [{"name": "Studio"}],
    "start_season": {"season": "spring", "year": 2024},
    "broadcast": {"day_of_the_week": "friday", "start_time": "23:00"},
    "source": "manga",
    "related_anime": [],
    "recommendations": [],
}


class CleanupUserMessagesTaskTests(TestCase):
    """Test cleanup of old shown user messages."""

    def setUp(self):
        """Create a user for task tests."""
        self.user = get_user_model().objects.create_user(
            username="test",
        )

    @override_settings(USER_MESSAGE_RETENTION_DAYS=30)
    def test_cleanup_user_messages_deletes_only_old_shown_messages(self):
        """Delete only shown messages older than the retention window."""
        now = timezone.now()
        old_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="old shown",
            shown_at=now - timedelta(days=31),
        )
        recent_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="recent shown",
            shown_at=now - timedelta(days=5),
        )
        unseen = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="unseen",
        )

        deleted_count = cleanup_user_messages()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(UserMessage.objects.filter(id=old_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=recent_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=unseen.id).exists())


class ImportAnimeFranchiseTaskTests(TestCase):
    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_calls_service_with_expected_kwargs(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.return_value = FranchiseImportStats(
            scanned=4,
            users_considered=3,
            distinct_seeds=2,
            due_selected=2,
            skipped_not_due=1,
            created=6,
            planned_creations=7,
            already_exists=1,
            state_rows_created=1,
            state_rows_updated=1,
            skipped=0,
            errors=0,
            created_ids=["100", "200"],
            cache_warm_targets=[
                {"media_id": "100", "kind": "root", "component_root_mal_id": "100"},
                {"media_id": "200", "kind": "root", "component_root_mal_id": "200"},
            ],
            cache_warm_scheduled=2,
            cache_warm_roots=["100", "200"],
            cache_warm_errors=0,
            discovery_errors=2,
        )

        result = import_anime_franchise(
            profile_key="satellites",
            full_rescan=True,
            refresh_cache=True,
            limit=10,
            user_ids=[1, 2],
        )

        mock_service_cls.return_value.run.assert_called_once_with(
            profile_key="satellites",
            dry_run=False,
            full_rescan=True,
            limit=10,
            refresh_cache=True,
            user_ids=[1, 2],
        )
        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "scanned": 4,
                "users_considered": 3,
                "distinct_seeds": 2,
                "due_selected": 2,
                "skipped_not_due": 1,
                "created": 6,
                "planned_creations": 7,
                "already_exists": 1,
                "state_rows_created": 1,
                "state_rows_updated": 1,
                "skipped": 0,
                "errors": 0,
                "created_ids": ["100", "200"],
                "cache_warm_targets": [
                    {"media_id": "100", "kind": "root", "component_root_mal_id": "100"},
                    {"media_id": "200", "kind": "root", "component_root_mal_id": "200"},
                ],
                "cache_warm_scheduled": 2,
                "cache_warm_built": 0,
                "cache_warm_skipped": 0,
                "cache_warm_roots": ["100", "200"],
                "cache_warm_errors": 0,
                "series_view_refreshes": 0,
                "series_view_refresh_errors": 0,
                "discovery_errors": 2,
            },
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    @patch("app.tasks.AnimeSeriesViewProjectionBuilder")
    @patch("app.tasks.AnimeFranchiseCacheBuildService")
    @patch("app.tasks.AnimeFranchiseBuildSession")
    def test_import_task_wires_single_build_session(
        self,
        build_session_class,
        cache_build_service_class,
        projection_builder_class,
        refresh_service_class,
        import_service_class,
        mock_cache,
    ):
        mock_cache.add.return_value = True
        build_session = build_session_class.return_value
        series_snapshot_service = (
            build_session.build_series_view_snapshot_service.return_value
        )
        import_service_class.return_value.run.return_value = FranchiseImportStats()

        import_anime_franchise(refresh_cache=True)

        build_session_class.assert_called_once_with(refresh_cache=True)
        projection_builder_class.assert_called_once_with(
            snapshot_service=series_snapshot_service,
        )
        cache_build_service_class.assert_called_once_with(
            build_session=build_session,
        )
        refresh_service_class.assert_called_once_with(
            projection_builder=projection_builder_class.return_value,
        )
        import_service_class.assert_called_once_with(
            build_session=build_session,
            snapshot_service=build_session.snapshot_service.return_value,
            cache_build_service=cache_build_service_class.return_value,
            series_view_refresh_service=refresh_service_class.return_value,
        )

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_returns_default_cache_warm_fields(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.return_value = FranchiseImportStats()

        result = import_anime_franchise(profile_key="satellites")

        self.assertEqual(result["cache_warm_targets"], [])
        self.assertEqual(result["cache_warm_scheduled"], 0)
        self.assertEqual(result["cache_warm_built"], 0)
        self.assertEqual(result["cache_warm_skipped"], 0)
        self.assertEqual(result["cache_warm_roots"], [])
        self.assertEqual(result["cache_warm_errors"], 0)
        self.assertEqual(result["series_view_refreshes"], 0)
        self.assertEqual(result["series_view_refresh_errors"], 0)
        self.assertEqual(result["discovery_errors"], 0)

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_skips_when_lock_already_exists(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = False

        result = import_anime_franchise(profile_key="satellites")

        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "skipped": True,
                "reason": "already_running",
            },
        )
        mock_service_cls.assert_not_called()
        mock_cache.delete.assert_not_called()

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_releases_lock_when_service_raises(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            import_anime_franchise(profile_key="satellites")

        mock_cache.add.assert_called_once_with(
            "anime-franchise-import:satellites",
            "1",
            timeout=60 * 60 * 6,
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")

    def test_build_mal_anime_franchise_payload_uses_shared_task_name(self):
        self.assertEqual(
            build_mal_anime_franchise_payload.name,
            MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
        )


class RefreshMALAnimeMetadataTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media_id = "38000"
        self.payload = {
            "media_id": self.media_id,
            "source": "mal",
            "media_type": "anime",
            "title": "Old Anime",
            "details": {},
            "related": {},
        }
        mal_cache.save_anime_cache(
            self.media_id,
            self.payload,
            fetched_at=timezone.now() - timedelta(days=10),
        )

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_success_returns_structured_result(
        self, mock_anime
    ):
        mock_anime.return_value = {**self.payload, "title": "New Anime"}

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(
            result,
            {"media_type": "anime", "media_id": self.media_id, "refreshed": True},
        )
        mock_anime.assert_called_once_with(self.media_id, refresh_cache=True)
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_refresh_attempt_at"])

    @patch(
        "events.services.anime_release_date_notifications."
        "AnimeReleaseDateNotificationService.process_metadata_refresh",
    )
    @patch("app.tasks.mal.anime")
    def test_refresh_passes_old_and_new_payloads_without_extra_mal_call(
        self,
        mock_anime,
        mock_process,
    ):
        new_payload = {**self.payload, "title": "New Anime"}
        mock_anime.return_value = new_payload

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertTrue(result["refreshed"])
        mock_anime.assert_called_once_with(self.media_id, refresh_cache=True)
        mock_process.assert_called_once_with(
            media_id=self.media_id,
            old_metadata=self.payload,
            new_metadata=new_payload,
            source="metadata_refresh",
        )

    @patch(
        "events.services.anime_release_date_notifications."
        "AnimeReleaseDateNotificationService.process_metadata_refresh",
        side_effect=RuntimeError("notification state unavailable"),
    )
    @patch("app.tasks.mal.anime")
    def test_release_date_hook_failure_does_not_fail_metadata_refresh(
        self,
        mock_anime,
        _mock_process,
    ):
        mock_anime.return_value = {**self.payload, "title": "New Anime"}

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertTrue(result["refreshed"])

    @patch("app.providers.mal.services.api_request", return_value=MAL_API_RESPONSE)
    def test_refresh_mal_anime_metadata_success_replaces_cache_and_clears_error(
        self, mock_api_request
    ):
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        meta["last_refresh_error_at"] = timezone.now().isoformat()
        meta["last_error_message"] = "timeout"
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(
            result,
            {"media_type": "anime", "media_id": self.media_id, "refreshed": True},
        )
        mock_api_request.assert_called_once()
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id))["title"],
            "Fresh Anime",
        )
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNone(meta["last_refresh_error_at"])
        self.assertEqual(meta["last_error_message"], "")

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_expected_error_preserves_stale_cache(
        self, mock_anime
    ):
        mock_anime.side_effect = requests.exceptions.Timeout("timeout")

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertFalse(result["refreshed"])
        self.assertEqual(result["error"], "timeout")
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id)), self.payload
        )
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_refresh_error_at"])
        self.assertEqual(meta["last_error_message"], "timeout")

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_duplicate_task_lock_skips(self, mock_anime):
        cache.add(
            mal_cache.get_anime_refresh_task_lock_key(self.media_id), "1", timeout=60
        )

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(result["reason"], "already_running")
        mock_anime.assert_not_called()

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_unexpected_error_releases_lock(
        self, mock_anime
    ):
        mock_anime.side_effect = RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            refresh_mal_anime_metadata(self.media_id)

        self.assertIsNone(
            cache.get(mal_cache.get_anime_refresh_task_lock_key(self.media_id))
        )

    @patch("app.tasks.mal.anime")
    def test_refresh_error_without_payload_does_not_create_fresh_meta(self, mock_anime):
        cache.delete(mal_cache.get_anime_cache_key(self.media_id))
        cache.delete(mal_cache.get_anime_cache_meta_key(self.media_id))
        mock_anime.side_effect = requests.exceptions.Timeout("timeout")

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertFalse(result["refreshed"])
        self.assertIsNone(cache.get(mal_cache.get_anime_cache_meta_key(self.media_id)))


class BuildMALAnimeFranchisePayloadTaskTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("app.tasks.AnimeFranchiseCacheBuildService")
    def test_build_task_delegates_to_cache_builder_and_cleans_locks(
        self, mock_service_class
    ):
        cache.add(anime_franchise_cache.get_queue_lock_key("100"), "1", timeout=60)
        mock_service_class.return_value.build_and_save.return_value = {
            "media_id": "100",
            "built": True,
        }

        result = build_mal_anime_franchise_payload("100")

        self.assertEqual(result, {"media_id": "100", "built": True})
        mock_service_class.return_value.build_and_save.assert_called_once_with("100")
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.AnimeFranchiseCacheBuildService")
    def test_build_task_lock_skips_duplicate(self, mock_service_class):
        cache.add(anime_franchise_cache.get_task_lock_key("100"), "1", timeout=60)

        result = build_mal_anime_franchise_payload("100")

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "already_running")
        mock_service_class.assert_not_called()
