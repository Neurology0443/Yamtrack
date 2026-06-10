# ruff: noqa: D101,D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import MediaTypes, Sources


class MALStaleCacheDetailViewTests(TestCase):
    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _metadata(self, media_type, source):
        return {
            "media_id": "1",
            "title": "Test",
            "media_type": media_type,
            "source": source,
            "image": "http://example.com/image.jpg",
            "related": {},
        }

    def _get(self, source, media_type):
        return self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": source,
                    "media_type": media_type,
                    "media_id": "1",
                    "title": "test",
                },
            ),
        )

    @patch("app.views.AnimeFranchiseService")
    @patch("app.providers.services.get_media_metadata")
    @override_settings(ANIME_FRANCHISE_GROUPING_ENABLED=False)
    def test_mal_anime_detail_enables_stale_refresh_options(
        self,
        mock_get_metadata,
        mock_franchise_service,
    ):
        mock_get_metadata.return_value = self._metadata(
            MediaTypes.ANIME.value, Sources.MAL.value
        )

        response = self._get(Sources.MAL.value, MediaTypes.ANIME.value)

        self.assertEqual(response.status_code, 200)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.ANIME.value,
            "1",
            Sources.MAL.value,
            allow_stale=True,
            schedule_stale_refresh=True,
        )
        mock_franchise_service.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    def test_mal_manga_detail_does_not_enable_stale_refresh_options(
        self, mock_get_metadata
    ):
        mock_get_metadata.return_value = self._metadata(
            MediaTypes.MANGA.value, Sources.MAL.value
        )

        response = self._get(Sources.MAL.value, MediaTypes.MANGA.value)

        self.assertEqual(response.status_code, 200)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.MANGA.value,
            "1",
            Sources.MAL.value,
            allow_stale=False,
            schedule_stale_refresh=False,
        )

    @patch("app.providers.services.get_media_metadata")
    def test_non_mal_provider_does_not_enable_stale_refresh_options(
        self, mock_get_metadata
    ):
        mock_get_metadata.return_value = self._metadata(
            MediaTypes.MOVIE.value, Sources.TMDB.value
        )

        response = self._get(Sources.TMDB.value, MediaTypes.MOVIE.value)

        self.assertEqual(response.status_code, 200)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
            allow_stale=False,
            schedule_stale_refresh=False,
        )

    @patch("app.providers.services.get_media_metadata")
    def test_manual_provider_does_not_enable_stale_refresh_options(
        self, mock_get_metadata
    ):
        mock_get_metadata.return_value = self._metadata(
            MediaTypes.BOOK.value, Sources.MANUAL.value
        )

        response = self._get(Sources.MANUAL.value, MediaTypes.BOOK.value)

        self.assertEqual(response.status_code, 200)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.BOOK.value,
            "1",
            Sources.MANUAL.value,
            allow_stale=False,
            schedule_stale_refresh=False,
        )
