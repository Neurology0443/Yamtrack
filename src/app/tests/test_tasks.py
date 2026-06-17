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
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_task_names import (
    MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
)
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
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
            cache_warm_targets=[
                {"media_id": "100", "kind": "root", "component_root_mal_id": "100"},
                {"media_id": "200", "kind": "root", "component_root_mal_id": "200"},
            ],
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
                "cache_warm_targets": [
                    {"media_id": "100", "kind": "root", "component_root_mal_id": "100"},
                    {"media_id": "200", "kind": "root", "component_root_mal_id": "200"},
                ],
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

        self.assertEqual(result["cache_warm_targets"], [])
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

    def _snapshot_for_task(self, media_id="100", *, canonical_media_id=None):
        node = AnimeNode(str(media_id), "Seed", "mal", "tv", "img", None, [])
        return AnimeFranchiseSnapshot(
            root_node=node,
            nodes_by_media_id={str(media_id): node},
            all_normalized_relations=[],
            continuity_component=[node],
            series_line=[node],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id=str(media_id),
            canonical_root_media_id=str(canonical_media_id or media_id),
        )

    def _set_payload_for_cache(
        self,
        mock_build_for_cache,
        payload,
        *,
        media_id="100",
        canonical_media_id=None,
    ):
        mock_build_for_cache.return_value = (
            self._snapshot_for_task(
                media_id,
                canonical_media_id=canonical_media_id,
            ),
            payload,
        )

    def _save_aliasable_canonical_payload(self):
        canonical_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "34161",
            "canonical_root_media_id": "34161",
            "display_title": "Season 1",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "34161",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Season 1",
                    },
                ],
            },
            "sections": [
                {
                    "key": "continuity_extras",
                    "title": "Main Story Extras",
                    "entries": [
                        {
                            "media_id": "34428",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Extra",
                        },
                    ],
                    "visible_in_ui": True,
                    "hidden_if_empty": True,
                },
            ],
            "aliasable_media_ids": ["34161", "34428"],
            "covered_media_ids": ["34161", "34428"],
        }
        anime_franchise_cache.save_payload("34161", canonical_payload)
        anime_franchise_cache.replace_aliases("34161", canonical_payload)
        return canonical_payload

    def _assert_no_direct_payload_alias_conflict(self, media_ids):
        for media_id in media_ids:
            direct = cache.get(anime_franchise_cache.get_payload_key(media_id))
            alias = cache.get(anime_franchise_cache.get_alias_key(media_id))
            self.assertFalse(direct and alias, media_id)

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_canonical_build_replaces_aliases_and_deletes_stale_direct_payloads(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        stale_direct_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "34428",
            "canonical_root_media_id": "34428",
            "display_title": "Old Direct",
            "series": {"key": "series", "title": "Series", "entries": []},
            "sections": [],
        }
        anime_franchise_cache.save_payload("34428", stale_direct_payload)
        payload = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "34161",
                "canonical_root_media_id": "34161",
                "display_title": "Season 1",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "34161",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Season 1",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "continuity_extras",
                        "title": "Main Story Extras",
                        "entries": [
                            {
                                "media_id": "34428",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "Extra",
                            },
                        ],
                    },
                ],
            },
        )()
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="34161")

        result = build_mal_anime_franchise_payload("34161")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "34161")
        self.assertIsNone(cache.get(anime_franchise_cache.get_payload_key("34428")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("34428")))
        lookup = anime_franchise_cache.load_payload_for_media("34428")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "34161")
        self.assertEqual(lookup.payload["root_media_id"], "34161")
        self._assert_no_direct_payload_alias_conflict(["34428"])

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_saves_payload_and_meta(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = True
        mock_graph_builder.truncation_reason = "max_nodes"
        cache.add(anime_franchise_cache.get_queue_lock_key("100"), "1", timeout=60)
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="100")

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
        mock_build_for_cache.assert_called_once_with("100", mock_graph_builder)
        self.assertEqual(result["node_count"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["truncation_reason"], "max_nodes")
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.anime_franchise_cache.maybe_schedule_build")
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_from_noncanonical_skips_canonical(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
        mock_maybe_schedule_build,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="269")

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["built"])
        self.assertEqual(result["media_id"], "269")
        self.assertEqual(result["canonical_media_id"], "223")
        self.assertEqual(result["alias_count"], 0)
        payload, _meta = anime_franchise_cache.load_payload("223")
        self.assertIsNone(payload)
        lookup = anime_franchise_cache.load_payload_for_media("269")
        self.assertFalse(lookup.alias_hit)
        mock_maybe_schedule_build.assert_called_once()

    @patch("app.tasks.anime_franchise_cache.maybe_schedule_build")
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_skips_aliases_for_noncanonical_seed(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
        mock_maybe_schedule_build,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 4
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="38040")

        result = build_mal_anime_franchise_payload("38040")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "30831")
        self.assertEqual(result["alias_count"], 0)
        alias = cache.get(anime_franchise_cache.get_alias_key("38040"))
        self.assertIsNone(alias)
        lookup = anime_franchise_cache.load_payload_for_media("38040")
        self.assertFalse(lookup.alias_hit)
        mock_maybe_schedule_build.assert_called_once()

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_truncated_build_skips_aliases(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = True
        mock_graph_builder.truncation_reason = "max_nodes"
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="269")

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["truncated"])
        self.assertEqual(result["canonical_media_id"], "269")
        self.assertEqual(result["alias_count"], 0)
        payload, _meta = anime_franchise_cache.load_payload("269")
        self.assertIsNotNone(payload)
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("223")
        self.assertIsNone(canonical_payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_aliases_disabled_saves_under_seed(
        self,
        mock_build_for_cache,
        mock_graph_builder_class,
    ):
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 2
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="269")

        result = build_mal_anime_franchise_payload("269")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "269")
        self.assertEqual(result["alias_count"], 0)
        payload, _meta = anime_franchise_cache.load_payload("269")
        self.assertIsNotNone(payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("223")
        self.assertIsNone(canonical_payload)

    @patch("app.tasks.anime_franchise_cache.maybe_schedule_build")
    @patch("app.tasks.AnimeFranchiseUiPipeline")
    @patch("app.tasks.AnimeFranchiseSnapshotService")
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    def test_build_mal_anime_franchise_payload_saves_scoped_seed_payload(
        self,
        mock_graph_builder_class,
        mock_snapshot_service_class,
        mock_ui_pipeline_class,
        mock_maybe_schedule_build,
    ):
        clean_canonical_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "11757",
            "canonical_root_media_id": "11757",
            "display_title": "Canonical",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "11757",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Canonical",
                    },
                ],
            },
            "sections": [],
        }
        anime_franchise_cache.save_payload("11757", clean_canonical_payload)
        relations = [
            AnimeRelation("40489", "36474", "full_story"),
            AnimeRelation("40489", "39597", "sequel"),
        ]
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        nodes = {
            "11757": AnimeNode("11757", "Canonical", "mal", "tv", "img", None, []),
            "36474": AnimeNode("36474", "Full Story", "mal", "tv", "img", None, []),
            "39597": AnimeNode("39597", "Sequel", "mal", "tv", "img", None, []),
            "40489": AnimeNode(
                "40489",
                "Special",
                "mal",
                "tv_special",
                "img",
                None,
                relations[:2],
            ),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["40489"],
            nodes_by_media_id=nodes,
            all_normalized_relations=relations,
            continuity_component=list(nodes.values()),
            series_line=[nodes["11757"], nodes["36474"], nodes["39597"]],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="40489",
            canonical_root_media_id="11757",
        )
        mock_snapshot_service_class.return_value.build.return_value = snapshot
        mock_ui_pipeline_class.return_value.run.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "40489",
                "canonical_root_media_id": "11757",
                "display_title": "Special",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "11757",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Canonical",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "specials",
                        "title": "Specials",
                        "entries": [
                            {
                                "media_id": "40489",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "Special",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("40489")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "11757")
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("11757")
        scoped_payload, _scoped_meta = anime_franchise_cache.load_payload("40489")
        self.assertEqual(canonical_payload["display_title"], "Canonical")
        self.assertEqual(canonical_payload["sections"], [])
        self.assertIsNotNone(scoped_payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("40489")))
        lookup = anime_franchise_cache.load_payload_for_media("40489")
        self.assertFalse(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "40489")
        self.assertEqual(lookup.payload["root_media_id"], "40489")
        self._assert_no_direct_payload_alias_conflict(["40489"])
        self.assertEqual(scoped_payload["series"]["entries"], [])
        related_ids = [
            entry["media_id"]
            for section in scoped_payload["sections"]
            if section["key"] == "related_series"
            for entry in section["entries"]
        ]
        self.assertEqual(related_ids, ["36474", "39597"])
        mock_maybe_schedule_build.assert_not_called()

    @patch("app.tasks.AnimeFranchiseUiPipeline")
    @patch("app.tasks.AnimeFranchiseSnapshotService")
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    def test_build_mal_anime_franchise_payload_skips_scoped_for_aliasable_seed(
        self,
        mock_graph_builder_class,
        mock_snapshot_service_class,
        mock_ui_pipeline_class,
    ):
        self._save_aliasable_canonical_payload()
        relation = AnimeRelation("34428", "29803", "sequel")
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        nodes = {
            "34161": AnimeNode("34161", "Season 1", "mal", "tv", "img", None, []),
            "34428": AnimeNode(
                "34428",
                "Extra",
                "mal",
                "tv_special",
                "img",
                None,
                [relation],
            ),
            "29803": AnimeNode("29803", "Related", "mal", "tv", "img", None, []),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["34428"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[relation],
            continuity_component=list(nodes.values()),
            series_line=[nodes["34161"]],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="34428",
            canonical_root_media_id="34161",
        )
        mock_snapshot_service_class.return_value.build.return_value = snapshot
        mock_ui_pipeline_class.return_value.run.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "34428",
                "canonical_root_media_id": "34161",
                "display_title": "Extra",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "34161",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Season 1",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "continuity_extras",
                        "title": "Main Story Extras",
                        "entries": [
                            {
                                "media_id": "34428",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "Extra",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("34428")

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "34161")
        canonical_payload, _canonical_meta = anime_franchise_cache.load_payload("34161")
        self.assertIsNotNone(canonical_payload)
        self.assertIn("34428", canonical_payload["aliasable_media_ids"])
        direct_payload, _direct_meta = anime_franchise_cache.load_payload("34428")
        self.assertIsNone(direct_payload)
        alias = cache.get(anime_franchise_cache.get_alias_key("34428"))
        self.assertIsNotNone(alias)
        self.assertEqual(alias["canonical_media_id"], "34161")
        lookup = anime_franchise_cache.load_payload_for_media("34428")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "34161")
        self.assertEqual(lookup.payload["root_media_id"], "34161")
        self._assert_no_direct_payload_alias_conflict(["34428"])

    @patch("app.tasks.AnimeFranchiseUiPipeline")
    @patch("app.tasks.AnimeFranchiseSnapshotService")
    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    def test_build_mal_anime_franchise_payload_deletes_old_direct_for_aliasable_seed(
        self,
        mock_graph_builder_class,
        mock_snapshot_service_class,
        mock_ui_pipeline_class,
    ):
        canonical_before = self._save_aliasable_canonical_payload()
        old_scoped_payload = {
            "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
            "root_media_id": "34428",
            "canonical_root_media_id": "34428",
            "display_title": "Old Scoped",
            "series": {"key": "series_line", "title": "Series", "entries": []},
            "sections": [],
        }
        anime_franchise_cache.save_payload("34428", old_scoped_payload)

        relation = AnimeRelation("34428", "29803", "sequel")
        mock_graph_builder = mock_graph_builder_class.return_value
        mock_graph_builder.node_count = 3
        mock_graph_builder.truncated = False
        mock_graph_builder.truncation_reason = ""
        nodes = {
            "34161": AnimeNode("34161", "Season 1", "mal", "tv", "img", None, []),
            "34428": AnimeNode(
                "34428",
                "Extra",
                "mal",
                "tv_special",
                "img",
                None,
                [relation],
            ),
            "29803": AnimeNode("29803", "Related", "mal", "tv", "img", None, []),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["34428"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[relation],
            continuity_component=list(nodes.values()),
            series_line=[nodes["34161"]],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="34428",
            canonical_root_media_id="34161",
        )
        mock_snapshot_service_class.return_value.build.return_value = snapshot
        mock_ui_pipeline_class.return_value.run.return_value = type(
            "FranchiseVM",
            (),
            {
                "root_media_id": "34428",
                "canonical_root_media_id": "34161",
                "display_title": "Extra",
                "series": {
                    "key": "series",
                    "title": "Series",
                    "entries": [
                        {
                            "media_id": "34161",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Season 1",
                        },
                    ],
                },
                "sections": [
                    {
                        "key": "continuity_extras",
                        "title": "Main Story Extras",
                        "entries": [
                            {
                                "media_id": "34428",
                                "source": "mal",
                                "media_type": "anime",
                                "title": "Extra",
                            },
                        ],
                    },
                ],
            },
        )()

        result = build_mal_anime_franchise_payload("34428")

        self.assertTrue(result["built"])
        self.assertIsNone(cache.get(anime_franchise_cache.get_payload_key("34428")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("34428")))
        lookup = anime_franchise_cache.load_payload_for_media("34428")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "34161")
        self.assertEqual(lookup.payload["root_media_id"], "34161")
        self._assert_no_direct_payload_alias_conflict(["34428"])
        canonical_after = cache.get(anime_franchise_cache.get_payload_key("34161"))
        self.assertEqual(
            canonical_after["display_title"],
            canonical_before["display_title"],
        )
        self.assertEqual(canonical_after["sections"], canonical_before["sections"])

    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_preserves_previous_payload_on_error(
        self,
        mock_build_for_cache,
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
        mock_build_for_cache.side_effect = RuntimeError("boom")

        result = build_mal_anime_franchise_payload("100")

        self.assertFalse(result["built"])
        payload, meta = anime_franchise_cache.load_payload("100")
        self.assertEqual(payload["display_title"], "Previous")
        self.assertEqual(meta["last_error_message"], "boom")
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks.AnimeFranchiseGraphBuilder")
    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_task_preserves_previous_payload_when_save_payload_rejects_invalid_payload(
        self,
        mock_build_for_cache,
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
        payload = type(
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
        self._set_payload_for_cache(mock_build_for_cache, payload, media_id="100")

        result = build_mal_anime_franchise_payload("100")

        self.assertFalse(result["built"])
        payload, meta = anime_franchise_cache.load_payload("100")
        self.assertEqual(payload["display_title"], "Previous")
        self.assertTrue(meta["last_error_message"])
        self.assertIsNone(cache.get(anime_franchise_cache.get_task_lock_key("100")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    @patch("app.tasks._build_mal_anime_franchise_payload_for_cache")
    def test_build_mal_anime_franchise_payload_task_lock_skips_duplicate(
        self,
        mock_build_for_cache,
    ):
        cache.add(anime_franchise_cache.get_task_lock_key("100"), "1", timeout=60)

        result = build_mal_anime_franchise_payload("100")

        self.assertTrue(result["skipped"])
        mock_build_for_cache.assert_not_called()
