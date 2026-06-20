# ruff: noqa: D102
from django.test import SimpleTestCase

from app.services.anime_series_view_refresh_queue import (
    normalize_media_ids,
    refresh_queue_lock_key,
)


class AnimeSeriesViewRefreshQueueTests(SimpleTestCase):
    """Test stable refresh queue normalization and keys."""

    def test_normalize_media_ids(self):
        self.assertEqual(normalize_media_ids(None), ())
        self.assertEqual(normalize_media_ids(""), ())
        self.assertEqual(normalize_media_ids("502"), ("502",))
        self.assertEqual(normalize_media_ids(" 502 "), ("502",))
        self.assertEqual(
            normalize_media_ids(["", None, "10", "2", "2"]),
            ("2", "10"),
        )

    def test_lock_key_is_order_independent(self):
        self.assertEqual(
            refresh_queue_lock_key(1, ["10", "2"]),
            refresh_queue_lock_key(1, ["2", "10"]),
        )
