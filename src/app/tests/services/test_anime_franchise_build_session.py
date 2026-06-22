# ruff: noqa: D101,D102
from django.test import SimpleTestCase

from app.services.anime_franchise_build_session import AnimeFranchiseHydrationContext


class AnimeFranchiseHydrationContextTests(SimpleTestCase):
    def test_memoizes_simple_fetch(self):
        calls = []
        payload = {"media_id": "123"}

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return payload

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)

        self.assertIs(context.fetch_anime("123"), payload)
        self.assertIs(context.fetch_anime("123"), payload)
        self.assertEqual(len(calls), 1)

    def test_forced_refresh_happens_once(self):
        calls = []
        payload = {"media_id": "123"}

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return payload

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)

        context.fetch_anime("123", refresh_cache=True)
        context.fetch_anime("123", refresh_cache=True)

        self.assertEqual(
            calls,
            [(
                "123",
                {
                    "refresh_cache": True,
                    "allow_stale": False,
                    "schedule_stale_refresh": False,
                },
            )],
        )

    def test_normal_read_reuses_refreshed_payload(self):
        calls = []
        refreshed = {"media_id": "123", "fresh": True}

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return refreshed

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)

        self.assertIs(context.fetch_anime("123", refresh_cache=True), refreshed)
        self.assertIs(context.fetch_anime("123", refresh_cache=False), refreshed)
        self.assertEqual(len(calls), 1)

    def test_normalizes_int_and_string_media_ids(self):
        calls = []
        payload = {"media_id": "123"}

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return payload

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)

        context.fetch_anime(123)
        context.fetch_anime("123")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "123")
