from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from app.models import (
    MediaTypes,
    Sources,
)


class MediaDetailsViewTests(TestCase):
    """Test the media details views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

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
        )

    @patch("app.views.AnimeFranchiseService")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_anime_franchise_not_enabled_for_non_mal_or_non_anime(
        self,
        mock_get_metadata,
        mock_anime_franchise_service,
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
        mock_anime_franchise_service.assert_not_called()

    @patch("app.views.AnimeFranchiseService")
    @patch("app.views.helpers.enrich_items_with_user_data")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_anime_franchise_enabled_for_mal_anime(
        self,
        mock_get_metadata,
        mock_enrich_items,
        mock_anime_franchise_service,
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
        mock_anime_franchise_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series_line_entries": [],
                "sections": [],
            },
        )()

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
        mock_anime_franchise_service.return_value.build.assert_called_once_with("100")
        self.assertNotIn("related_anime", response.context["media"]["related"])
        self.assertIn("recommendations", response.context["media"]["related"])

    @patch("app.views.AnimeFranchiseService")
    @patch("app.views.helpers.enrich_items_with_user_data")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=True)
    def test_mal_anime_grouping_removes_legacy_related_anime_only(
        self,
        mock_get_metadata,
        mock_enrich_items,
        mock_anime_franchise_service,
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
        mock_anime_franchise_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "100",
                "display_title": "Test Anime",
                "series_line_entries": [
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
                    }
                ],
                "sections": [
                    type(
                        "FranchiseSection",
                        (),
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
                        },
                    )()
                ],
            },
        )()

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
        mock_anime_franchise_service.return_value.build.assert_called_once_with("100")
        self.assertContains(response, "Season 1")
        self.assertContains(response, "Spin Off Alpha")

    @patch("app.views.AnimeFranchiseService")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=False)
    def test_anime_franchise_disabled_by_setting(
        self,
        mock_get_metadata,
        mock_anime_franchise_service,
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
        mock_anime_franchise_service.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    @patch("app.providers.tmdb.process_episodes")
    def test_season_details_view(self, mock_process_episodes, mock_get_metadata):
        """Test the season details view."""
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

        mock_get_metadata.assert_called_once_with(
            "tv_with_seasons",
            "1668",
            Sources.TMDB.value,
            [1],
        )
