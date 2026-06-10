from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from app.models import (
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from app.services import anime_franchise_cache


class MediaDetailsViewTests(TestCase):
    """Test the media details views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        cache.clear()

    @patch("app.providers.services.get_media_metadata")
    def test_media_details_view(self, mock_get_metadata):
        """Test the media details view."""
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "http://example.com/image.jpg",
            "overview": "Test overview",
            "release_date": "2023-01-01",
        }

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Test Movie")

        mock_get_metadata.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "238",
            Sources.TMDB.value,
            allow_stale=False,
            schedule_stale_refresh=False,
        )

    @patch("app.views.anime_franchise_cache.load_payload_for_media")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_anime_franchise_not_enabled_for_non_mal_or_non_anime(
        self,
        mock_get_metadata,
        mock_load_payload_for_media,
    ):
        """Anime franchise grouping should only run for MAL anime details."""
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "http://example.com/image.jpg",
            "related": {},
        }

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        mock_load_payload_for_media.assert_not_called()

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.views.helpers.enrich_items_with_user_data")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_anime_franchise_enabled_for_mal_anime(
        self,
        mock_get_metadata,
        mock_enrich_items,
        mock_build_delay,
    ):
        """Anime franchise grouping should be injected for MAL anime details."""
        mock_enrich_items.side_effect = (
            lambda request, items, section_name: [  # noqa: ARG005
                {"item": item, "media": None} for item in items
            ]
        )
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy Related",
                        "image": "http://example.com/legacy.jpg",
                    },
                    {
                        "media_id": "150",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Spin Off Alpha",
                        "image": "http://example.com/spinoff.jpg",
                        "relation_type": "spin_off",
                    },
                ],
                "recommendations": [
                    {
                        "media_id": "102",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy Recommendation",
                        "image": "http://example.com/reco.jpg",
                    }
                ],
            },
        }
        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        mock_build_delay.assert_called_once_with("100")
        self.assertIn("related_anime", response.context["media"]["related"])
        self.assertIn("recommendations", response.context["media"]["related"])

    @patch("app.views.helpers.enrich_items_with_user_data")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_grouping_removes_legacy_related_anime_only(
        self,
        mock_get_metadata,
        mock_enrich_items,
    ):
        """Regression guard for dedup between franchise and legacy related_anime."""
        mock_enrich_items.side_effect = (
            lambda request, items, section_name: [  # noqa: ARG005
                {"item": item, "media": None} for item in items
            ]
        )
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy Related",
                        "image": "http://example.com/legacy.jpg",
                    }
                ],
                "recommendations": [
                    {
                        "media_id": "102",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy Recommendation",
                        "image": "http://example.com/reco.jpg",
                    }
                ],
            },
        }
        anime_franchise_cache.save_payload(
            "100",
            {
                "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series": {"key": "series", "title": "Series", "entries": [
                    {
                        "media_id": "100",
                        "source": "mal",
                        "media_type": "anime",
                        "anime_media_type": "tv",
                        "title": "Test Anime",
                        "image": "http://example.com/image.jpg",
                        "relation_type": None,
                        "linked_series_line_media_id": None,
                        "linked_series_line_index": None,
                        "is_current": True,
                    },
                    {
                        "media_id": "101",
                        "source": "mal",
                        "media_type": "anime",
                        "anime_media_type": "tv",
                        "title": "Test Anime Season 2",
                        "image": "http://example.com/image-2.jpg",
                        "relation_type": None,
                        "linked_series_line_media_id": None,
                        "linked_series_line_index": None,
                        "is_current": False,
                    }
                ]},
                "sections": [
                    {
                        "key": "related_series",
                        "title": "Related Series",
                        "entries": [
                            {
                                "media_id": "150",
                                "source": "mal",
                                "media_type": "anime",
                                "anime_media_type": "tv",
                                "title": "Spin Off Alpha",
                                "image": "http://example.com/spinoff.jpg",
                                "relation_type": "spin_off",
                                "linked_series_line_media_id": "100",
                                "linked_series_line_index": 0,
                                "is_current": False,
                            }
                        ],
                        "visible_in_ui": True,
                        "hidden_if_empty": True,
                    }
                ],
                "truncated": False,
                "node_count": 3,
            },
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("anime_franchise", response.context)
        self.assertNotIn("related_anime", response.context["media"]["related"])
        self.assertIn("recommendations", response.context["media"]["related"])
        self.assertContains(response, "Series")
        self.assertContains(response, "Test Anime")
        self.assertContains(response, "Test Anime Season 2")
        self.assertContains(response, "Related Series")
        self.assertContains(response, "Spin Off Alpha")
        self.assertContains(response, "Spin Off")
        self.assertContains(response, 'data-franchise-badge="true"', count=2)
        self.assertContains(response, 'data-franchise-badge-type="relation"', count=1)
        self.assertContains(response, 'data-franchise-badge-value="spin_off"', count=1)
        self.assertContains(response, 'data-franchise-badge-type="format"', count=1)
        self.assertContains(response, 'data-franchise-badge-value="tv"', count=1)
        self.assertContains(response, 'data-franchise-badge-active="true"', count=0)
        self.assertContains(response, 'data-franchise-badge-active="false"', count=2)
        self.assertContains(response, "Legacy Recommendation")


    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_stale_franchise_payload_is_displayed_and_refreshed(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Stale franchise payloads should render while refreshing in background."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        anime_franchise_cache.save_payload(
            "100",
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "100",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Test Anime",
                            "image": "img",
                        },
                    ],
                },
                "sections": [],
            },
            fetched_at=timezone.now() - timedelta(days=31),
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["anime_franchise"])
        self.assertNotIn("related_anime", response.context["media"]["related"])
        mock_build_delay.assert_called_once_with("100")

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_invalid_franchise_payload_keeps_fallback_and_rebuilds(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Invalid franchise payloads should be ignored without hiding fallback."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        cache.set(
            anime_franchise_cache.get_payload_key("100"),
            {
                "schema_version": 999,
                "root_media_id": "100",
                "display_title": "Bad",
                "series": {},
                "sections": [],
            },
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        self.assertIn("related_anime", response.context["media"]["related"])
        mock_build_delay.assert_called_once_with("100")


    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_malformed_cached_payload_keeps_related_anime(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Malformed cached franchise payloads should not break detail pages."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        cache.set(
            anime_franchise_cache.get_payload_key("100"),
            {
                "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
                "root_media_id": "100",
                "display_title": "Bad",
                "series": {"entries": []},
                "sections": [{"entries": []}],
            },
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        self.assertIn("related_anime", response.context["media"]["related"])
        mock_build_delay.assert_called_once_with("100")

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_empty_cached_payload_keeps_related_anime(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """A valid but empty cached payload should not hide fallback relations."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        anime_franchise_cache.save_payload(
            "100",
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series": {"key": "series", "title": "Series", "entries": []},
                "sections": [],
            },
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        self.assertIn("related_anime", response.context["media"]["related"])
        mock_build_delay.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_valid_cached_payload_without_related_does_not_crash(
        self,
        mock_get_metadata,
    ):
        """Cached franchise rendering should not require a related metadata key."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
        }
        anime_franchise_cache.save_payload(
            "100",
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "100",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Test Anime",
                            "image": "img",
                        },
                    ],
                },
                "sections": [],
            },
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["anime_franchise"])

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_recent_error_blocks_rebuild_on_cache_miss(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Recent franchise build errors should suppress immediate retries."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        anime_franchise_cache.mark_error("100", "boom")

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("related_anime", response.context["media"]["related"])
        mock_build_delay.assert_not_called()

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_queue_lock_blocks_duplicate_enqueue_from_view(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """An existing queue lock should keep fallback visible without a message."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        cache.add(anime_franchise_cache.get_queue_lock_key("100"), "1", timeout=60)

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("related_anime", response.context["media"]["related"])
        self.assertNotContains(response, "Franchise complète en préparation")
        mock_build_delay.assert_not_called()



    def _canonical_alias_payload(self):
        return {
            "root_media_id": "223",
            "display_title": "Dragon Ball",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "223",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball",
                        "image": "img",
                    },
                    {
                        "media_id": "269",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball GT",
                        "image": "img",
                    },
                ],
            },
            "sections": [],
            "aliasable_media_ids": ["223", "269"],
        }

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_alias_hit_displays_payload_without_fallback(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Alias hits should render complete payloads without fallback/build."""
        mock_get_metadata.return_value = {
            "media_id": "269",
            "title": "Dragon Ball GT",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "img",
            "related": {
                "related_anime": [
                    {
                        "media_id": "223",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Dragon Ball",
                        "image": "img",
                    },
                ],
            },
        }
        payload = self._canonical_alias_payload()
        anime_franchise_cache.save_payload("223", payload)
        anime_franchise_cache.replace_aliases("223", payload)

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "269",
                    "title": "dragon-ball-gt",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["anime_franchise"])
        mock_fallback_payload.assert_not_called()
        mock_build_delay.assert_not_called()
        self.assertNotIn("related_anime", response.context["media"]["related"])

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_stale_alias_hit_refreshes_canonical_id(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Stale alias hits should enqueue refreshes for canonical IDs."""
        mock_get_metadata.return_value = {
            "media_id": "269",
            "title": "Dragon Ball GT",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "img",
            "related": {},
        }
        payload = self._canonical_alias_payload()
        anime_franchise_cache.save_payload(
            "223",
            payload,
            fetched_at=timezone.now() - timedelta(days=31),
        )
        anime_franchise_cache.replace_aliases("223", payload)

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "269",
                    "title": "dragon-ball-gt",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        mock_build_delay.assert_called_once_with("223")

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_alias_hit_recomputes_current_entry_from_visited_page(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Alias-rendered payloads should not trust cached is_current flags."""
        mock_get_metadata.return_value = {
            "media_id": "269",
            "title": "Dragon Ball GT",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "img",
            "related": {},
        }
        payload = self._canonical_alias_payload()
        payload["series"]["entries"][0]["is_current"] = True
        payload["series"]["entries"][1]["is_current"] = False
        anime_franchise_cache.save_payload("223", payload)
        anime_franchise_cache.replace_aliases("223", payload)

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "269",
                    "title": "dragon-ball-gt",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        entries = response.context["anime_franchise"]["series"]["entries"]
        self.assertFalse(entries[0]["item"]["is_current"])
        self.assertTrue(entries[1]["item"]["is_current"])
        mock_build_delay.assert_not_called()

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_broken_alias_resumes_cache_miss_flow(
        self,
        mock_get_metadata,
        mock_build_delay,
    ):
        """Broken aliases should be deleted and fall back to requested IDs."""
        mock_get_metadata.return_value = {
            "media_id": "269",
            "title": "Dragon Ball GT",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "img",
            "related": {
                "related_anime": [
                    {
                        "media_id": "223",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Dragon Ball",
                        "image": "img",
                        "relation_type": "prequel",
                    },
                ],
            },
        }
        mock_fallback_payload.return_value = None
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "269",
                    "title": "dragon-ball-gt",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        mock_fallback_payload.assert_called_once()
        mock_build_delay.assert_called_once_with("269")

    @patch("app.views.anime_franchise_cache.maybe_schedule_build")
    @patch("app.views.prepare_anime_franchise_context")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_cached_payload_prepare_error_schedules_rebuild_once(
        self,
        mock_get_metadata,
        mock_prepare_context,
        mock_maybe_schedule_build,
    ):
        """A render error should not trigger both error and stale scheduling."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {
                "related_anime": [
                    {
                        "media_id": "101",
                        "media_type": "anime",
                        "source": "mal",
                        "title": "Legacy",
                        "image": "img",
                    },
                ],
            },
        }
        anime_franchise_cache.save_payload(
            "100",
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "100",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Test Anime",
                            "image": "img",
                        },
                    ],
                },
                "sections": [],
            },
            fetched_at=timezone.now() - timedelta(days=31),
        )
        mock_prepare_context.side_effect = RuntimeError("render boom")
        mock_maybe_schedule_build.return_value = True

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        self.assertIn("related_anime", response.context["media"]["related"])
        mock_maybe_schedule_build.assert_called_once()

    @patch("app.views.anime_franchise_cache.load_payload_for_media")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=False)
    def test_anime_franchise_disabled_by_setting(
        self,
        mock_get_metadata,
        mock_load_payload_for_media,
    ):
        """Feature should remain disabled when the setting is false."""
        mock_get_metadata.return_value = {
            "media_id": "100",
            "title": "Test Anime",
            "media_type": MediaTypes.ANIME.value,
            "source": Sources.MAL.value,
            "image": "http://example.com/image.jpg",
            "related": {"related_anime": []},
        }

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "media_id": "100",
                    "title": "test-anime",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["anime_franchise"])
        mock_load_payload_for_media.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    @patch("app.providers.tmdb.process_episodes")
    def test_season_details_view(self, mock_process_episodes, mock_get_metadata):
        """Test the season details view."""
        self.user.obfuscate_unseen_episodes = True
        self.user.save(update_fields=["obfuscate_unseen_episodes"])

        mock_get_metadata.return_value = {
            "title": "Test TV Show",
            "media_id": "1668",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "image": "http://example.com/image.jpg",
            "season/1": {
                "title": "Season 1",
                "media_id": "1668",
                "media_type": MediaTypes.SEASON.value,
                "source": Sources.TMDB.value,
                "image": "http://example.com/season.jpg",
                "episodes": [],
            },
        }

        mock_process_episodes.return_value = [
            {
                "media_id": "1668",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.EPISODE.value,
                "season_number": 1,
                "episode_number": 1,
                "title": "Episode 1",
                "name": "Episode 1",
                "air_date": "2023-01-01",
                "watched": False,
            },
        ]

        response = self.client.get(
            reverse(
                "season_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_id": "1668",
                    "title": "test-tv-show",
                    "season_number": 1,
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Season 1")
        self.assertEqual(len(response.context["media"]["episodes"]), 1)
        self.assertContains(response, "line-clamp-1 blur cursor-pointer")

        mock_get_metadata.assert_called_once_with(
            "tv_with_seasons",
            "1668",
            Sources.TMDB.value,
            [1],
        )

    @patch("app.providers.services.get_media_metadata")
    def test_media_details_refreshes_missing_item_image(self, mock_get_metadata):
        """Item.image is updated when missing and live metadata has one."""
        live_image = "http://example.com/fresh.jpg"
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": live_image,
            "max_progress": 1,
            "overview": "Test overview",
            "release_date": "2023-01-01",
        }

        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image=settings.IMG_NONE,
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.image, live_image)

    @patch("app.providers.services.get_media_metadata")
    def test_media_details_keeps_existing_item_image(self, mock_get_metadata):
        """Item.image is left alone when already set."""
        existing_image = "http://example.com/stored.jpg"
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "image": "http://example.com/fresh.jpg",
            "max_progress": 1,
            "overview": "Test overview",
            "release_date": "2023-01-01",
        }

        item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image=existing_image,
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.image, existing_image)
