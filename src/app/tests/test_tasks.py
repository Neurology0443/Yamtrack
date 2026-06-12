# ruff: noqa: D101,D102
from datetime import timedelta
from unittest.mock import patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import UserMessage, UserMessageLevel
from app.providers import mal_cache
from app.services import anime_franchise_cache
from app.services.anime_franchise_import import FranchiseImportStats
from app.services.anime_franchise_task_names import (
    MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
)
from app.tasks import (
    build_mal_anime_franchise_payload,
    cleanup_user_messages,
    import_anime_franchise,
    refresh_mal_anime_metadata,
)

MAL_API_RESPONSE = {
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


class CleanupUserMessagesTaskTests(TestCase):
    """Test cleanup of old shown user messages."""

    def setUp(self):
        """Create a user for task tests."""
        self.user = get_user_model().objects.create_user(
            username="test",
        )

    @override_settings(USER_MESSAGE_RETENTION_DAYS=30)
    def test_cleanup_user_messages_deletes_only_old_shown_messages(self):
        """Delete only shown messages older than the retention window."""
        now = timezone.now()
        old_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="old shown",
            shown_at=now - timedelta(days=31),
        )
        recent_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="recent shown",
            shown_at=now - timedelta(days=5),
        )
        unseen = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="unseen",
        )

        deleted_count = cleanup_user_messages()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(UserMessage.objects.filter(id=old_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=recent_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=unseen.id).exists())


class ImportAnimeFranchiseTaskTests(TestCase):
    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_calls_service_with_expected_kwargs(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.return_value = FranchiseImportStats(
            scanned=4,
            users_considered=3,
            distinct_seeds=2,
            due_selected=2,
            skipped_not_due=1,
            created=6,
            planned_creations=7,
            already_exists=1,
            state_rows_created=1,
            state_rows_updated=1,
            skipped=0,
            errors=0,
            created_ids=["100", "200"],
            cache_warm_scheduled=2,
            cache_warm_roots=["100", "200"],
            cache_warm_errors=0,
        )

        result = import_anime_franchise(
            profile_key="satellites",
            full_rescan=True,
            refresh_cache=True,
            limit=10,
            user_ids=[1, 2],
        )

        mock_service_cls.return_value.run.assert_called_once_with(
            profile_key="satellites",
            dry_run=False,
            full_rescan=True,
            limit=10,
            refresh_cache=True,
            user_ids=[1, 2],
        )
        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "scanned": 4,
                "users_considered": 3,
                "distinct_seeds": 2,
                "due_selected": 2,
                "skipped_not_due": 1,
                "created": 6,
                "planned_creations": 7,
                "already_exists": 1,
                "state_rows_created": 1,
                "state_rows_updated": 1,
                "skipped": 0,
                "errors": 0,
                "created_ids": ["100", "200"],
                "cache_warm_scheduled": 2,
                "cache_warm_roots": ["100", "200"],
                "cache_warm_errors": 0,
            },
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_returns_default_cache_warm_fields(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.return_value = FranchiseImportStats()

        result = import_anime_franchise(profile_key="satellites")

        self.assertEqual(result["cache_warm_scheduled"], 0)
        self.assertEqual(result["cache_warm_roots"], [])
        self.assertEqual(result["cache_warm_errors"], 0)

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_skips_when_lock_already_exists(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = False

        result = import_anime_franchise(profile_key="satellites")

        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "skipped": True,
                "reason": "already_running",
            },
        )
        mock_service_cls.assert_not_called()
        mock_cache.delete.assert_not_called()

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_releases_lock_when_service_raises(
        self, mock_service_cls, mock_cache
    ):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            import_anime_franchise(profile_key="satellites")

        mock_cache.add.assert_called_once_with(
            "anime-franchise-import:satellites",
            "1",
            timeout=60 * 60 * 6,
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")

    def test_build_mal_anime_franchise_payload_uses_shared_task_name(self):
        self.assertEqual(
            build_mal_anime_franchise_payload.name,
            MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
        )


class RefreshMALAnimeMetadataTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media_id = "38000"
        self.payload = {
            "media_id": self.media_id,
            "source": "mal",
            "media_type": "anime",
            "title": "Old Anime",
            "details": {},
            "related": {},
        }
        mal_cache.save_anime_cache(
            self.media_id,
            self.payload,
            fetched_at=timezone.now() - timedelta(days=10),
        )

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_success_returns_structured_result(
        self, mock_anime
    ):
        mock_anime.return_value = {**self.payload, "title": "New Anime"}

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(
            result,
            {"media_type": "anime", "media_id": self.media_id, "refreshed": True},
        )
        mock_anime.assert_called_once_with(self.media_id, refresh_cache=True)
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_refresh_attempt_at"])

    @patch("app.providers.mal.services.api_request", return_value=MAL_API_RESPONSE)
    def test_refresh_mal_anime_metadata_success_replaces_cache_and_clears_error(
        self, mock_api_request
    ):
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        meta["last_refresh_error_at"] = timezone.now().isoformat()
        meta["last_error_message"] = "timeout"
        cache.set(mal_cache.get_anime_cache_meta_key(self.media_id), meta)

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(
            result,
            {"media_type": "anime", "media_id": self.media_id, "refreshed": True},
        )
        mock_api_request.assert_called_once()
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id))["title"],
            "Fresh Anime",
        )
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNone(meta["last_refresh_error_at"])
        self.assertEqual(meta["last_error_message"], "")

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_expected_error_preserves_stale_cache(
        self, mock_anime
    ):
        mock_anime.side_effect = requests.exceptions.Timeout("timeout")

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertFalse(result["refreshed"])
        self.assertEqual(result["error"], "timeout")
        self.assertEqual(
            cache.get(mal_cache.get_anime_cache_key(self.media_id)), self.payload
        )
        meta = cache.get(mal_cache.get_anime_cache_meta_key(self.media_id))
        self.assertIsNotNone(meta["last_refresh_error_at"])
        self.assertEqual(meta["last_error_message"], "timeout")

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_duplicate_task_lock_skips(self, mock_anime):
        cache.add(
            mal_cache.get_anime_refresh_task_lock_key(self.media_id), "1", timeout=60
        )

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertEqual(result["reason"], "already_running")
        mock_anime.assert_not_called()

    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_unexpected_error_releases_lock(
        self, mock_anime
    ):
        mock_anime.side_effect = RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            refresh_mal_anime_metadata(self.media_id)

        self.assertIsNone(
            cache.get(mal_cache.get_anime_refresh_task_lock_key(self.media_id))
        )

    @patch("app.tasks.mal.anime")
    def test_refresh_error_without_payload_does_not_create_fresh_meta(self, mock_anime):
        cache.delete(mal_cache.get_anime_cache_key(self.media_id))
        cache.delete(mal_cache.get_anime_cache_meta_key(self.media_id))
        mock_anime.side_effect = requests.exceptions.Timeout("timeout")

        result = refresh_mal_anime_metadata(self.media_id)

        self.assertFalse(result["refreshed"])
        self.assertIsNone(cache.get(mal_cache.get_anime_cache_meta_key(self.media_id)))


class BuildMALAnimeFranchisePayloadTaskTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_saves_payload_and_meta(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = True
        mock_graph_builder.truncation_reason = "max_nodes"
        cache.add(anime_franchise_cache.get_queue_lock_key("100"), "1", timeout=60)
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "100",
                "display_title": "Root",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "100",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Root",
                        },
                    ],
                },
                "sections": [],
            },
        )()

        result = build_mal_anime_franchise_payload("100")

        self.assertTrue(result["built"])
        payload, meta = anime_franchise_cache.load_payload("100")
        self.assertEqual(payload["root_media_id"], "100")
        self.assertEqual(meta["last_error_message"], "")
        self.assertEqual(meta["node_count"], 2)
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["truncation_reason"], "max_nodes")
        mock_graph_builder_class.assert_called_once_with(
            max_nodes=settings.ANIME_FRANCHISE_MAX_NODES,
        )
        mock_service.assert_called_once_with(graph_builder=mock_graph_builder)
        mock_service.return_value.build.assert_called_once_with("100")
        self.assertEqual(result["node_count"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncation_reason"], "max_nodes")
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_from_noncanonical_saves_canonical(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "269",
                "display_title": "Dragon Ball GT",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "223",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball",
                        },
                        {
                            "media_id": "269",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball GT",
                        },
                    ],
                },
                "sections": [],
            },
        )()

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["built"])
        self.assertEqual(result["media_id"], "269")
        self.assertEqual(result["canonical_media_id"], "223")
        self.assertGreaterEqual(result["alias_count"], 1)
        payload, _meta = anime_franchise_cache.load_payload("223")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["root_media_id"], "223")
        self.assertIn("269", payload["aliasable_media_ids"])
        lookup = anime_franchise_cache.load_payload_for_media("269")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "223")

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_aliases_continuity_extra_seed(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 4
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "38040",
                "display_title": "KonoSuba Movie: Kurenai Densetsu",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "30831",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "KonoSuba",
                        },
                        {
                            "media_id": "32937",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "KonoSuba 2",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "continuity_extras",
                        "title": "Main Story Extras",
                        "entries": [
                            {
                                "media_id": "38040",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "KonoSuba Movie: Kurenai Densetsu",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("38040")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "30831")
        self.assertGreaterEqual(result["alias_count"], 1)
        alias = cache.get(anime_franchise_cache.get_alias_key("38040"))
        self.assertIsNotNone(alias)
        self.assertEqual(alias["canonical_media_id"], "30831")
        lookup = anime_franchise_cache.load_payload_for_media("38040")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "30831")

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_truncated_build_skips_aliases(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = True
        mock_graph_builder.truncation_reason = "max_nodes"
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "269",
                "display_title": "Dragon Ball GT",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "223",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball",
                        },
                        {
                            "media_id": "269",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball GT",
                        },
                    ],
                },
                "sections": [],
            },
        )()

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["truncated"])
        self.assertEqual(result["canonical_media_id"], "269")
        self.assertEqual(result["alias_count"], 0)
        payload, _meta = anime_franchise_cache.load_payload("269")
        self.assertIsNotNone(payload)
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("223")
        self.assertIsNone(canonical_payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_creates_special_context_refs(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "28121",
                "display_title": "DanMachi",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "28121",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "DanMachi",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "specials",
                        "title": "Specials",
                        "entries": [
                            {
                                "media_id": "32801",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "DanMachi OVA",
                            },
                        ],
                    },
                    {
                        "key": "related_series",
                        "title": "Related Series",
                        "entries": [
                            {
                                "media_id": "32887",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "Sword Oratoria",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("28121")

        self.assertTrue(result["built"])
        self.assertEqual(result["context_ref_count"], 1)
        self.assertEqual(result["alias_count"], 0)
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_context_key("32801")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_context_key("32887")))

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_truncated_cleans_context_refs(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        cache.set(anime_franchise_cache.get_context_index_key("28121"), ["32801"])
        cache.set(
            anime_franchise_cache.get_context_key("32801"),
            anime_franchise_cache._build_context_record(
                canonical_media_id="28121",
                context_media_id="32801",
                section_key="specials",
            ),
        )
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = True
        mock_graph_builder.truncation_reason = "max_nodes"
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "28121",
                "display_title": "DanMachi",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "28121",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "DanMachi",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "specials",
                        "title": "Specials",
                        "entries": [
                            {
                                "media_id": "32801",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "DanMachi OVA",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("28121")

        self.assertTrue(result["built"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["context_ref_count"], 0)
        self.assertIsNone(cache.get(anime_franchise_cache.get_context_key("32801")))

    @override_settings(ANIME_FRANCHISE_CONTEXT_LOOKUP_ENABLED=False)
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_context_lookup_disabled_cleans_refs(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        cache.set(anime_franchise_cache.get_context_index_key("28121"), ["32801"])
        cache.set(
            anime_franchise_cache.get_context_key("32801"),
            anime_franchise_cache._build_context_record(
                canonical_media_id="28121",
                context_media_id="32801",
                section_key="specials",
            ),
        )
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "28121",
                "display_title": "DanMachi",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "28121",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "DanMachi",
                        },
                        {
                            "media_id": "28122",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "DanMachi II",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "specials",
                        "title": "Specials",
                        "entries": [
                            {
                                "media_id": "32801",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "DanMachi OVA",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("28121")

        self.assertTrue(result["built"])
        self.assertEqual(result["context_ref_count"], 0)
        self.assertGreaterEqual(result["alias_count"], 1)
        self.assertIsNone(cache.get(anime_franchise_cache.get_context_key("32801")))
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_context_index_key("28121")),
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_aliases_disabled_saves_under_seed(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "269",
                "display_title": "Dragon Ball GT",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "223",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball",
                        },
                        {
                            "media_id": "269",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball GT",
                        },
                    ],
                },
                "sections": [],
            },
        )()

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "269")
        self.assertEqual(result["alias_count"], 0)
        payload, _meta = anime_franchise_cache.load_payload("269")
        self.assertIsNotNone(payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("223")
        self.assertIsNone(canonical_payload)

    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_preserves_previous_payload_on_error(
        self,
        mock_service,
    ):
        previous_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "100",
            "display_title": "Previous",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "100",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Previous",
                    },
                ],
            },
            "sections": [],
            "truncated": False,
            "node_count": 1,
        }
        anime_franchise_cache.save_payload("100", previous_payload)
        mock_service.return_value.build.side_effect = RuntimeError("boom")

        result = build_mal_anime_franchise_payload("100")

        self.assertFalse(result["built"])
        payload, meta = anime_franchise_cache.load_payload("100")
        self.assertEqual(payload["display_title"], "Previous")
        self.assertEqual(meta["last_error_message"], "boom")
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks.AnimeFranchiseService")
    def test_task_preserves_previous_payload_when_save_payload_rejects_invalid_payload(
        self,
        mock_service,
        mock_graph_builder_class,
    ):
        previous_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "100",
            "display_title": "Previous",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "100",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Previous",
                    },
                ],
            },
            "sections": [],
            "truncated": False,
            "node_count": 1,
        }
        anime_franchise_cache.save_payload("100", previous_payload)
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 1
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        mock_service.return_value.build.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "100",
                "display_title": "Broken",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "100",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Broken",
                            "bad": object(),
                        },
                    ],
                },
                "sections": [],
            },
        )()

        result = build_mal_anime_franchise_payload("100")

        self.assertFalse(result["built"])
        payload, meta = anime_franchise_cache.load_payload("100")
        self.assertEqual(payload["display_title"], "Previous")
        self.assertTrue(meta["last_error_message"])
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.AnimeFranchiseService")
    def test_build_mal_anime_franchise_payload_task_lock_skips_duplicate(
        self,
        mock_service,
    ):
        cache.add(anime_franchise_cache.get_task_lock_key("100"), "1", timeout=60)

        result = build_mal_anime_franchise_payload("100")

        self.assertTrue(result["skipped"])
        mock_service.assert_not_called()
