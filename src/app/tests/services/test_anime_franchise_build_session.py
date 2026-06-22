# ruff: noqa: D101,D102
from django.test import SimpleTestCase

from app.services.anime_franchise_build_session import (
    AnimeFranchiseBuildSession,
    AnimeFranchiseHydrationContext,
)


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


class AnimeFranchiseBuildSessionTests(SimpleTestCase):
    def test_fetch_anime_uses_session_refresh_default(self):
        calls = []

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return self._metadata(media_id)

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)
        session = AnimeFranchiseBuildSession(
            refresh_cache=True,
            hydration_context=context,
        )

        session.fetch_anime("123")

        self.assertEqual(calls[0][1]["refresh_cache"], True)

    def test_fetch_anime_allows_refresh_override(self):
        calls = []

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return self._metadata(media_id)

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)
        session = AnimeFranchiseBuildSession(
            refresh_cache=True,
            hydration_context=context,
        )

        session.fetch_anime("123", refresh_cache=False)

        self.assertEqual(calls[0][1]["refresh_cache"], False)

    def test_anime_minimal_reuses_hydrated_metadata(self):
        calls = []

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return self._metadata(media_id)

        context = AnimeFranchiseHydrationContext(anime_fetcher=fetcher)
        session = AnimeFranchiseBuildSession(hydration_context=context)

        session.fetch_anime("123")
        minimal = session.anime_minimal("123")

        self.assertEqual(len(calls), 1)
        self.assertEqual(minimal["media_id"], "123")
        self.assertEqual(minimal["details"]["status"], "finished_airing")

    def test_anime_minimal_hydrates_once_when_called_repeatedly(self):
        calls = []

        def fetcher(media_id, **kwargs):
            calls.append((media_id, kwargs))
            return self._metadata(media_id)

        session = AnimeFranchiseBuildSession(
            hydration_context=AnimeFranchiseHydrationContext(anime_fetcher=fetcher),
        )

        session.anime_minimal(123)
        session.anime_minimal("123")

        self.assertEqual(len(calls), 1)

    def _metadata(self, media_id):
        return {
            "media_id": str(media_id),
            "title": "Example",
            "source": "mal",
            "media_type": "anime",
            "image": "https://example.com/image.jpg",
            "details": {
                "raw_media_type": "tv",
                "start_date": "2020-01-01",
                "status": "finished_airing",
            },
        }
