# ruff: noqa: D101, D102

from django.test import SimpleTestCase

from app.services.anime_series_view_refresh_queue import normalize_media_ids


class AnimeSeriesViewRefreshQueueTests(SimpleTestCase):
    def test_normalize_media_ids_handles_none(self):
        self.assertEqual(normalize_media_ids(None), ())

    def test_normalize_media_ids_handles_empty_string(self):
        self.assertEqual(normalize_media_ids(""), ())

    def test_normalize_media_ids_treats_raw_string_as_one_id(self):
        self.assertEqual(normalize_media_ids("502"), ("502",))

    def test_normalize_media_ids_strips_raw_string(self):
        self.assertEqual(normalize_media_ids(" 502 "), ("502",))

    def test_normalize_media_ids_deduplicates_and_sorts_iterables(self):
        self.assertEqual(
            normalize_media_ids(["", None, "10", "2", "2"]),
            ("2", "10"),
        )
