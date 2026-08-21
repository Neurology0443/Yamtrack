# ruff: noqa: D101, D102

from unittest.mock import patch

from django.test import SimpleTestCase

from anime.tasks import refresh_anime_metadata


class RefreshAnimeMetadataTaskTests(SimpleTestCase):
    def test_task_delegates_to_refresh_use_case(self):
        with patch("anime.tasks.RefreshAnimeMetadata") as use_case:
            refresh_anime_metadata.run(42)
        use_case.return_value.execute.assert_called_once_with(42)
