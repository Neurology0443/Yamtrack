# ruff: noqa: D101, D102

from unittest.mock import patch

from django.test import SimpleTestCase
from kombu.exceptions import OperationalError as BrokerOperationalError

from anime.enqueue import enqueue_anime_metadata_refresh


class EnqueueAnimeMetadataRefreshTests(SimpleTestCase):
    @patch("anime.tasks.refresh_anime_metadata.apply_async")
    def test_publication_disables_broker_retry(self, apply_async):
        enqueue_anime_metadata_refresh(42)
        apply_async.assert_called_once_with(args=(42,), retry=False)

    @patch("anime.tasks.refresh_anime_metadata.apply_async")
    def test_invalid_id_is_rejected_before_publication(self, apply_async):
        invalid_media_id = True
        with self.assertRaisesRegex(ValueError, "positive integer"):
            enqueue_anime_metadata_refresh(invalid_media_id)
        apply_async.assert_not_called()

    def test_expected_broker_failures_are_absorbed(self):
        for error in (BrokerOperationalError("broker unavailable"), ConnectionError()):
            with (
                self.subTest(error=type(error).__name__),
                patch(
                    "anime.tasks.refresh_anime_metadata.apply_async",
                    side_effect=error,
                ),
            ):
                enqueue_anime_metadata_refresh(42)

    @patch(
        "anime.tasks.refresh_anime_metadata.apply_async",
        side_effect=RuntimeError("programming bug"),
    )
    def test_unexpected_publication_failure_remains_visible(self, _apply_async):
        with self.assertRaisesRegex(RuntimeError, "programming bug"):
            enqueue_anime_metadata_refresh(42)
