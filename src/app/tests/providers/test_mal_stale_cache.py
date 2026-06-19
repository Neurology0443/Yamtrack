# ruff: noqa: D101,D102
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import MediaTypes, Sources
from app.providers import mal, mal_cache

API_RESPONSE = {
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


@override_settings(
    MAL_CACHE_FRESH_DAYS=7,
    MAL_CACHE_KEEP_DAYS=365,
    MAL_CACHE_RETRY_AFTER_ERROR_HOURS=12,
    MAL_CACHE_REFRESH_MIN_INTERVAL_HOURS=24,
)
class MALAnimeStaleCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media_id = "38000"
        self.payload = {
            "media_id": self.media_id,
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Cached Anime",
            "details": {
                "raw_media_type": "tv",
                "start_date": "2024-01-01",
                "status": "Finished",
            },
            "related": {},
        }

    def _save_payload_with_meta(self, *, fetched_delta):
        fetched_at = timezone.now() - fetched_delta
        mal_cache.save_anime_cache(self.media_id, self.payload, fetched_at=fetched_at)
        return cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))

    @patch("app.providers.mal_cache.maybe_schedule_refresh")
    @patch("app.providers.mal.services.api_request")
    def test_fresh_anime_cache_returns_cached_payload_without_api_or_refresh(
        self,
        mock_api_request,
        mock_schedule,
    ):
        self._save_payload_with_meta(fetched_delta=timedelta(days=1))

        result = mal.anime(
            self.media_id,
            allow_stale=True,
            schedule_stale_refresh=True,
        )

        self.assertEqual(result, self.payload)
        mock_api_request.assert_not_called()
        mock_schedule.assert_not_called()
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_accessed_at"])

    @patch("app.providers.mal_cache.maybe_schedule_refresh")
    @patch("app.providers.mal.services.api_request")
    def test_stale_anime_cache_with_allow_stale_returns_cached_and_schedules_once(
        self,
        mock_api_request,
        mock_schedule,
    ):
        self._save_payload_with_meta(fetched_delta=timedelta(days=10))

        result = mal.anime(
            self.media_id,
            allow_stale=True,
            schedule_stale_refresh=True,
        )

        self.assertEqual(result, self.payload)
        mock_api_request.assert_not_called()
        mock_schedule.assert_called_once()

    @patch("app.providers.mal.services.api_request", return_value=API_RESPONSE)
    def test_stale_anime_cache_without_allow_stale_fetches_synchronously(
        self, mock_api_request
    ):
        old_meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))

        result = mal.anime(self.media_id, allow_stale=False)

        self.assertEqual(result["title"], "Fresh Anime")
        mock_api_request.assert_called_once()
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id))["title"],
            "Fresh Anime",
        )
        new_meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertNotEqual(new_meta["fetched_at"], old_meta["fetched_at"])

    @patch("app.providers.mal.services.api_request", return_value=API_RESPONSE)
    def test_missing_anime_cache_fetches_and_stores_payload_and_meta(
        self, mock_api_request
    ):
        result = mal.anime(self.media_id)

        self.assertEqual(result["title"], "Fresh Anime")
        mock_api_request.assert_called_once()
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id))["title"],
            "Fresh Anime",
        )
        self.assertIsNotNone(
            cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))["fetched_at"]
        )

    @patch("app.providers.mal.services.api_request")
    def test_existing_payload_without_meta_is_upgraded_lazily(self, mock_api_request):
        cache.set(mal_cache.get_anime_cache_key(self.media_id), self.payload)

        result = mal.anime(self.media_id, allow_stale=True)

        self.assertEqual(result, self.payload)
        mock_api_request.assert_not_called()
        self.assertIsNotNone(
            cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        )

    @patch("app.providers.mal.services.api_request", return_value=API_RESPONSE)
    def test_refresh_cache_bypasses_cache_and_clears_error_meta(self, mock_api_request):
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))
        meta["last_refresh_error_at"] = timezone.now().isoformat()
        meta["last_error_message"] = "timeout"
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        result = mal.anime(self.media_id, refresh_cache=True)

        self.assertEqual(result["title"], "Fresh Anime")
        mock_api_request.assert_called_once()
        new_meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNone(new_meta["last_refresh_error_at"])
        self.assertEqual(new_meta["last_error_message"], "")

    @patch("app.providers.mal.services.api_request", return_value=API_RESPONSE)
    def test_invalid_meta_timestamp_is_stale_without_crashing(self, mock_api_request):
        mal_cache.save_anime_cache(self.media_id, self.payload)
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        meta["fetched_at"] = "not a datetime"
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        result = mal.anime(self.media_id, allow_stale=False)

        self.assertEqual(result["title"], "Fresh Anime")
        mock_api_request.assert_called_once()

    @patch("app.providers.mal_cache.cache")
    def test_touch_anime_cache_falls_back_when_touch_is_unavailable(self, mock_cache):
        mock_cache.touch.side_effect = NotImplementedError
        mock_cache.get.return_value = self.payload

        mal_cache.touch_anime_cache(self.media_id, payload=self.payload, meta={})

        mock_cache.set.assert_any_call(
            mal_cache.get_anime_cache_key(self.media_id),
            self.payload,
            timeout=mal_cache.get_keep_ttl_seconds(),
        )

    @patch("app.tasks.refresh_mal_anime_metadata")
    def test_enqueue_failure_deletes_queue_lock(self, mock_task):
        mock_task.delay.side_effect = RuntimeError("broker down")
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))

        scheduled = mal_cache.maybe_schedule_refresh(self.media_id, meta=meta)

        self.assertFalse(scheduled)
        self.assertFalse(cache.get(mal_cache.get_anime_refresh_lock_key(self.media_id)))

    @patch("app.providers.mal_cache.mark_refresh_attempt")
    @patch("app.tasks.refresh_mal_anime_metadata")
    def test_mark_refresh_attempt_failure_deletes_queue_lock(
        self, mock_task, mock_mark_attempt
    ):
        mock_mark_attempt.side_effect = RuntimeError("cache down")
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))

        scheduled = mal_cache.maybe_schedule_refresh(self.media_id, meta=meta)

        self.assertFalse(scheduled)
        mock_task.delay.assert_called_once_with(self.media_id)
        self.assertFalse(cache.get(mal_cache.get_anime_refresh_lock_key(self.media_id)))

    @patch("app.tasks.refresh_mal_anime_metadata")
    def test_successful_enqueue_marks_attempt_and_keeps_queue_lock(self, mock_task):
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))

        scheduled = mal_cache.maybe_schedule_refresh(self.media_id, meta=meta)

        self.assertTrue(scheduled)
        mock_task.delay.assert_called_once_with(self.media_id)
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_refresh_attempt_at"])
        self.assertEqual(
            cache.get(mal_cache.get_anime_refresh_lock_key(self.media_id)),
            "1",
        )

    @patch("app.providers.mal_cache.maybe_schedule_refresh")
    @patch("app.providers.mal.services.api_request")
    def test_import_helpers_use_cache_without_scheduling_refresh(
        self, mock_api_request, mock_schedule
    ):
        payload = {
            **self.payload,
            "title": "Cached Anime",
            "image": "http://example.com/anime.jpg",
            "details": {
                "raw_media_type": "tv",
                "start_date": "2024-01-01",
                "status": "Finished",
            },
            "related": {
                "related_anime": [
                    {
                        "media_id": "2",
                        "title": "Related",
                        "source": Sources.MAL.value,
                        "media_type": MediaTypes.ANIME.value,
                        "image": "http://example.com/related.jpg",
                        "relation_type": "sequel",
                    }
                ]
            },
        }
        mal_cache.save_anime_cache(self.media_id, payload)

        minimal = mal.anime_minimal(self.media_id)
        relations = mal.anime_relations(self.media_id)

        self.assertEqual(minimal["title"], "Cached Anime")
        self.assertEqual(minimal["details"]["start_date"], "2024-01-01")
        self.assertEqual(minimal["details"]["status"], "Finished")
        self.assertEqual(relations[0]["media_id"], "2")
        mock_api_request.assert_not_called()
        mock_schedule.assert_not_called()

    @patch("app.tasks.refresh_mal_anime_metadata")
    def test_recent_refresh_attempt_prevents_duplicate_schedule(self, mock_task):
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))
        meta["last_refresh_attempt_at"] = (
            timezone.now() - timedelta(hours=1)
        ).isoformat()
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        scheduled = mal_cache.maybe_schedule_refresh(self.media_id, meta=meta)

        self.assertFalse(scheduled)
        mock_task.delay.assert_not_called()

    @patch("app.tasks.refresh_mal_anime_metadata")
    def test_recent_refresh_error_prevents_schedule(self, mock_task):
        meta = self._save_payload_with_meta(fetched_delta=timedelta(days=10))
        meta["last_refresh_error_at"] = (
            timezone.now() - timedelta(hours=1)
        ).isoformat()
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        scheduled = mal_cache.maybe_schedule_refresh(self.media_id, meta=meta)

        self.assertFalse(scheduled)
        mock_task.delay.assert_not_called()

    @patch("app.providers.mal.services.api_request")
    def test_manga_cache_behavior_remains_unchanged(self, mock_api_request):
        manga_payload = {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.MANGA.value,
            "title": "Cached Manga",
        }
        cache.set("mal_manga_1", manga_payload)

        result = mal.manga("1")

        self.assertEqual(result, manga_payload)
        mock_api_request.assert_not_called()
        with self.assertRaises(TypeError):
            mal.manga("1", allow_stale=True)

    @patch("app.providers.mal_cache.maybe_schedule_refresh")
    @patch(
        "app.providers.mal.services.api_request",
        return_value={
            "data": [{"node": {"id": 1, "title": "Cowboy", "media_type": "tv"}}]
        },
    )
    def test_manga_and_search_do_not_use_anime_stale_refresh(
        self, mock_api_request, mock_schedule
    ):
        mal.search(MediaTypes.ANIME.value, "cowboy", 1)

        mock_api_request.assert_called_once()
        mock_schedule.assert_not_called()
        self.assertIsNone(cache.get("search_mal_anime_cowboy_1:meta"))
