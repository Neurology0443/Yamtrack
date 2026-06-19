# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import TestCase

from app.models import (
    Anime,
    AnimeLocalSeriesMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services import anime_franchise_cache
from app.services.anime_franchise_cache_warmer import (
    schedule_mal_anime_franchise_cache_warm,
)
from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryStats
from app.services.anime_franchise_import import AnimeFranchiseImportService
from app.services.anime_local_series_constants import (
    LOCAL_SERIES_VIEW_PROFILE_KEY,
)
from app.services.anime_local_series_projection import (
    AnimeLocalSeriesProjectionService,
    AnimeLocalSeriesProjectionStats,
)
from app.services.anime_local_series_resolver import (
    LocalSeriesGroup,
    LocalSeriesResolution,
)
from events.models import AnimeReleaseDateScanState


class AnimeFranchiseImportNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="import-user")

    def tearDown(self):
        cache.clear()

    def _build_service(
        self,
        media_ids,
        *,
        due_seeds=None,
        root_ids=None,
        selections=None,
        cache_warm_scheduler=None,
        discovery_service=None,
    ):
        due_seeds = due_seeds or [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="321")
        ]
        root_ids = root_ids or ["321"] * len(due_seeds)
        selections = selections or [
            SimpleNamespace(
                media_ids=media_ids,
                fingerprint_payload={"key": "value"},
            )
        ]

        snapshots = [
            SimpleNamespace(continuity_component=[f"component-{index}"])
            for index, _seed in enumerate(due_seeds)
        ]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = snapshots

        state_service = Mock()
        state_service.select_due_seeds.return_value = (due_seeds, 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)

        profile = Mock()
        profile.select.side_effect = selections
        profile.component_root_media_id.side_effect = root_ids
        profile.detail_cache_warm_media_ids.return_value = set()

        return AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=cache_warm_scheduler,
            discovery_service=discovery_service,
        ), profile

    def _assert_cache_warm_stats_invariant(self, stats):
        self.assertEqual(stats.cache_warm_scheduled, len(stats.cache_warm_targets))

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_newly_created_anime_schedules_notification_and_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
            "details": {
                "start_date": "2027-05",
                "status": "Upcoming",
            },
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        created_anime = Anime.objects.get(
            user=self.user,
            item__media_id="123",
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
        )
        self.assertEqual(created_anime.status, Status.PLANNING.value)
        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.created_ids, ["123"])
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(
            stats.cache_warm_targets,
            [
                {
                    "media_id": "321",
                    "kind": "root",
                    "component_root_mal_id": "321",
                }
            ],
        )
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_errors, 0)
        release_date_state = AnimeReleaseDateScanState.objects.get(
            item=created_anime.item,
        )
        self.assertEqual(
            release_date_state.last_seen_start_date_text,
            "2027-05",
        )
        self.assertEqual(release_date_state.last_seen_mal_status, "Upcoming")
        self._assert_cache_warm_stats_invariant(stats)
        cache_warm_scheduler.assert_called_once_with("321")
        mock_notify.assert_called_once_with(
            user_id=self.user.id,
            media_label=str(created_anime),
        )

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_existing_anime_does_not_schedule_notification_or_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        item = Item.objects.create(
            media_id="123",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Existing Anime",
            image="http://example.com/image.jpg",
        )
        Anime.objects.create(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )

        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.already_exists, 1)
        self.assertEqual(stats.created, 0)
        self.assertEqual(stats.cache_warm_scheduled, 0)
        self.assertEqual(stats.cache_warm_targets, [])
        self.assertEqual(stats.cache_warm_roots, [])
        cache_warm_scheduler.assert_not_called()
        mock_notify.assert_not_called()
        mock_anime_minimal.assert_not_called()

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multiple_creations_for_same_root_schedule_single_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123", "124"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Anime 123", "image": "http://example.com/123.jpg"},
            {"title": "Anime 124", "image": "http://example.com/124.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self._assert_cache_warm_stats_invariant(stats)
        cache_warm_scheduler.assert_called_once_with("321")

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_satellite_creation_schedules_root_and_detail_cache_warms(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        profile.detail_cache_warm_media_ids.return_value = {"123"}
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Satellite Anime",
            "image": "http://example.com/123.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(cache_warm_scheduler.call_args_list[0].args, ("321",))
        self.assertEqual(cache_warm_scheduler.call_args_list[1].args, ("123",))
        self.assertEqual(
            stats.cache_warm_targets,
            [
                {"media_id": "321", "kind": "root", "component_root_mal_id": "321"},
                {"media_id": "123", "kind": "detail", "component_root_mal_id": "321"},
            ],
        )
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_scheduled, 2)
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_continuity_profile_schedules_root_warm_only(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        profile.detail_cache_warm_media_ids.return_value = set()
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Continuity Anime",
            "image": "http://example.com/123.jpg",
        }

        stats = service.run(
            profile_key="continuity",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        cache_warm_scheduler.assert_called_once_with("321")
        self.assertEqual(
            stats.cache_warm_targets,
            [
                {"media_id": "321", "kind": "root", "component_root_mal_id": "321"},
            ],
        )
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_complete_profile_schedules_detail_only_for_satellite_like_created_ids(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123", "124"}, cache_warm_scheduler=cache_warm_scheduler
        )
        profile.detail_cache_warm_media_ids.side_effect = [set(), {"124"}]
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Continuity Anime", "image": "http://example.com/123.jpg"},
            {"title": "Satellite Anime", "image": "http://example.com/124.jpg"},
        ]

        stats = service.run(
            profile_key="complete",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            [call.args for call in cache_warm_scheduler.call_args_list],
            [("321",), ("124",)],
        )
        self.assertEqual(
            stats.cache_warm_targets,
            [
                {"media_id": "321", "kind": "root", "component_root_mal_id": "321"},
                {"media_id": "124", "kind": "detail", "component_root_mal_id": "321"},
            ],
        )
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_detail_cache_warm_dedup_skips_root_media_id(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"321"}, cache_warm_scheduler=cache_warm_scheduler
        )
        profile.detail_cache_warm_media_ids.return_value = {"321"}
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Root Anime",
            "image": "http://example.com/321.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        cache_warm_scheduler.assert_called_once_with("321")
        self.assertEqual(
            stats.cache_warm_targets,
            [
                {"media_id": "321", "kind": "root", "component_root_mal_id": "321"},
            ],
        )
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_cache_warm_dedup_promotes_detail_target_to_root(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="100"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="500"),
        ]
        selections = [
            SimpleNamespace(media_ids={"500"}, fingerprint_payload={"seed": "100"}),
            SimpleNamespace(media_ids={"600"}, fingerprint_payload={"seed": "500"}),
        ]
        service, profile = self._build_service(
            set(),
            due_seeds=due_seeds,
            root_ids=["100", "500"],
            selections=selections,
            cache_warm_scheduler=cache_warm_scheduler,
        )
        profile.detail_cache_warm_media_ids.side_effect = [{"500"}, set()]
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Satellite 500", "image": "http://example.com/500.jpg"},
            {"title": "Root Child 600", "image": "http://example.com/600.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            [call.args for call in cache_warm_scheduler.call_args_list],
            [("100",), ("500",)],
        )
        self.assertEqual(
            [
                target
                for target in stats.cache_warm_targets
                if target["media_id"] == "500"
            ],
            [
                {
                    "media_id": "500",
                    "kind": "root",
                    "component_root_mal_id": "500",
                }
            ],
        )
        self.assertIn("500", stats.cache_warm_roots)
        self.assertEqual(stats.cache_warm_scheduled, 2)
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_cache_warm_dedup_keeps_root_when_detail_seen_later(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="500"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="700"),
        ]
        selections = [
            SimpleNamespace(media_ids={"600"}, fingerprint_payload={"seed": "500"}),
            SimpleNamespace(media_ids={"500"}, fingerprint_payload={"seed": "700"}),
        ]
        service, profile = self._build_service(
            set(),
            due_seeds=due_seeds,
            root_ids=["500", "700"],
            selections=selections,
            cache_warm_scheduler=cache_warm_scheduler,
        )
        profile.detail_cache_warm_media_ids.side_effect = [set(), {"500"}]
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Root Child 600", "image": "http://example.com/600.jpg"},
            {"title": "Later Detail 500", "image": "http://example.com/500.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            [call.args for call in cache_warm_scheduler.call_args_list],
            [("500",), ("700",)],
        )
        self.assertEqual(
            [
                target
                for target in stats.cache_warm_targets
                if target["media_id"] == "500"
            ],
            [
                {
                    "media_id": "500",
                    "kind": "root",
                    "component_root_mal_id": "500",
                }
            ],
        )
        self.assertEqual(stats.cache_warm_roots.count("500"), 1)
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_cache_warm_dedup_keeps_single_detail_target(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="100"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="200"),
        ]
        selections = [
            SimpleNamespace(media_ids={"500"}, fingerprint_payload={"seed": "100"}),
            SimpleNamespace(media_ids={"501"}, fingerprint_payload={"seed": "200"}),
        ]
        service, profile = self._build_service(
            set(),
            due_seeds=due_seeds,
            root_ids=["100", "200"],
            selections=selections,
            cache_warm_scheduler=cache_warm_scheduler,
        )
        profile.detail_cache_warm_media_ids.side_effect = [{"900"}, {"900"}]
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Satellite 500", "image": "http://example.com/500.jpg"},
            {"title": "Satellite 501", "image": "http://example.com/501.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            [call.args for call in cache_warm_scheduler.call_args_list],
            [("100",), ("900",), ("200",)],
        )
        self.assertEqual(
            [
                target
                for target in stats.cache_warm_targets
                if target["media_id"] == "900"
            ],
            [
                {
                    "media_id": "900",
                    "kind": "detail",
                    "component_root_mal_id": "100",
                }
            ],
        )
        self.assertEqual(stats.cache_warm_scheduled, 3)
        self._assert_cache_warm_stats_invariant(stats)

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multiple_due_seeds_for_same_root_schedule_single_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="321"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="322"),
        ]
        selections = [
            SimpleNamespace(media_ids={"123"}, fingerprint_payload={"seed": "321"}),
            SimpleNamespace(media_ids={"124"}, fingerprint_payload={"seed": "322"}),
        ]
        service, profile = self._build_service(
            set(),
            due_seeds=due_seeds,
            root_ids=["321", "321"],
            selections=selections,
            cache_warm_scheduler=cache_warm_scheduler,
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Anime 123", "image": "http://example.com/123.jpg"},
            {"title": "Anime 124", "image": "http://example.com/124.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        cache_warm_scheduler.assert_called_once_with("321")

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multiple_roots_schedule_one_cache_warm_per_root(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="321"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="400"),
        ]
        selections = [
            SimpleNamespace(media_ids={"123"}, fingerprint_payload={"seed": "321"}),
            SimpleNamespace(media_ids={"401"}, fingerprint_payload={"seed": "400"}),
        ]
        service, profile = self._build_service(
            set(),
            due_seeds=due_seeds,
            root_ids=["321", "400"],
            selections=selections,
            cache_warm_scheduler=cache_warm_scheduler,
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Anime 123", "image": "http://example.com/123.jpg"},
            {"title": "Anime 401", "image": "http://example.com/401.jpg"},
        ]

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.cache_warm_scheduled, 2)
        self.assertEqual(set(stats.cache_warm_roots), {"321", "400"})
        self.assertEqual(cache_warm_scheduler.call_count, 2)
        cache_warm_scheduler.assert_any_call("321")
        cache_warm_scheduler.assert_any_call("400")

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_dry_run_does_not_schedule_notification_or_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.planned_creations, 1)
        self.assertEqual(stats.created, 0)
        self.assertEqual(stats.cache_warm_scheduled, 0)
        self.assertEqual(stats.cache_warm_targets, [])
        self.assertEqual(stats.cache_warm_roots, [])
        self._assert_cache_warm_stats_invariant(stats)
        self.assertFalse(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )
        cache_warm_scheduler.assert_not_called()
        mock_notify.assert_not_called()
        mock_anime_minimal.assert_not_called()

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_scheduler_return_value_is_ignored(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock(return_value=False)
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_errors, 0)
        cache_warm_scheduler.assert_called_once_with("321")
        self.assertTrue(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_deferred_scheduler_registration_is_not_counted_as_error(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        registered_roots = []

        def deferred_scheduler(root_media_id: str) -> None:
            transaction.on_commit(lambda: registered_roots.append(root_media_id))

        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=deferred_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            stats = service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=False,
                limit=None,
                refresh_cache=False,
                user_ids=[self.user.id],
            )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_errors, 0)
        self.assertEqual(registered_roots, [])
        self.assertEqual(len(callbacks), 1)

    @patch("app.services.anime_franchise_cache_warmer.current_app.send_task")
    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_existing_queue_lock_is_not_counted_as_cache_warm_error(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
        mock_send_task,
    ):
        cache.add(
            anime_franchise_cache.get_queue_lock_key("321"),
            "1",
            timeout=anime_franchise_cache.get_queue_lock_ttl_seconds(),
        )
        service, profile = self._build_service(
            {"123"},
            cache_warm_scheduler=schedule_mal_anime_franchise_cache_warm,
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        with self.captureOnCommitCallbacks(execute=True):
            stats = service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=False,
                limit=None,
                refresh_cache=False,
                user_ids=[self.user.id],
            )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_errors, 0)
        mock_send_task.assert_not_called()

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_partial_error_after_creation_still_schedules_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock()
        service, profile = self._build_service(
            {"123", "124"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile

        def anime_minimal_side_effect(media_id, **_kwargs):
            if media_id == "123":
                return {"title": "Anime 123", "image": "http://example.com/123.jpg"}
            cache_warm_scheduler.assert_called_once_with("321")
            error_message = "boom"
            raise RuntimeError(error_message)

        mock_anime_minimal.side_effect = anime_minimal_side_effect

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.cache_warm_scheduled, 1)
        self.assertEqual(stats.cache_warm_roots, ["321"])
        cache_warm_scheduler.assert_called_once_with("321")
        self.assertTrue(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )
        self.assertFalse(
            Anime.objects.filter(user=self.user, item__media_id="124").exists()
        )

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_scheduler_error_does_not_break_import(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock(side_effect=RuntimeError("boom"))
        service, profile = self._build_service(
            {"123"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.return_value = {
            "title": "Import Anime",
            "image": "http://example.com/image.jpg",
        }

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.cache_warm_errors, 1)
        self.assertEqual(stats.cache_warm_scheduled, 0)
        self.assertEqual(stats.cache_warm_targets, [])
        self.assertEqual(stats.cache_warm_roots, [])
        self._assert_cache_warm_stats_invariant(stats)
        self.assertTrue(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )


class AnimeFranchiseImportDiscoveryHardeningTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="discovery-import-user"
        )

    def _build_service(self, *, discovery_service, media_ids=None):
        if media_ids is None:
            media_ids = {"123"}
        due_seed = SimpleNamespace(user_id=self.user.id, seed_mal_id="321")
        snapshot = SimpleNamespace(continuity_component=["component"])
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot

        state_service = Mock()
        state_service.select_due_seeds.return_value = ([due_seed], 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)

        profile = Mock()
        profile.select.return_value = SimpleNamespace(
            media_ids=media_ids,
            fingerprint_payload={"key": "value"},
        )
        profile.component_root_media_id.return_value = "321"
        profile.detail_cache_warm_media_ids.return_value = set()

        return (
            AnimeFranchiseImportService(
                snapshot_service=snapshot_service,
                state_service=state_service,
                cache_warm_scheduler=Mock(),
                discovery_service=discovery_service,
            ),
            profile,
            state_service,
        )

    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_dry_run_passes_planned_import_ids_to_discovery(
        self,
        mock_get_profile,
        mock_anime_minimal,
    ):
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = AnimeFranchiseDiscoveryStats(
            processed_roots=1,
            visible_candidates=1,
            discoveries_seen=1,
            notifications_suppressed=1,
            suppressed_imported_in_same_run=1,
        )
        service, profile, _state_service = self._build_service(
            discovery_service=discovery_service
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        mock_anime_minimal.assert_not_called()
        self.assertFalse(Anime.objects.exists())
        self.assertEqual(stats.planned_creations, 1)
        discovery_service.process_snapshot.assert_called_once()
        self.assertEqual(
            discovery_service.process_snapshot.call_args.kwargs["imported_media_ids"],
            {"123"},
        )

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_discovery_error_records_state_without_import_error(
        self,
        mock_get_profile,
    ):
        discovery_service = Mock()
        discovery_service.process_snapshot.side_effect = RuntimeError("boom")
        service, profile, state_service = self._build_service(
            discovery_service=discovery_service,
            media_ids=set(),
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.errors, 0)
        self.assertEqual(stats.discovery_errors, 1)
        state_service.record_success.assert_called_once()
        discovery_service.record_error.assert_called_once()
        self.assertEqual(
            discovery_service.record_error.call_args.kwargs["component_root_mal_id"],
            "321",
        )

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_discovery_record_error_failure_remains_best_effort(
        self,
        mock_get_profile,
    ):
        discovery_service = Mock()
        discovery_service.process_snapshot.side_effect = RuntimeError("process boom")
        discovery_service.record_error.side_effect = RuntimeError("record boom")
        service, profile, state_service = self._build_service(
            discovery_service=discovery_service,
            media_ids=set(),
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.discovery_errors, 1)
        self.assertEqual(stats.errors, 0)
        state_service.record_success.assert_called_once()
        discovery_service.record_error.assert_called_once()

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_imported_media_ids_are_scoped_per_snapshot_root(
        self,
        mock_get_profile,
    ):
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = AnimeFranchiseDiscoveryStats()
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="321"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="654"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            SimpleNamespace(continuity_component=["a"]),
            SimpleNamespace(continuity_component=["b"]),
        ]
        state_service = Mock()
        state_service.select_due_seeds.return_value = (due_seeds, 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)
        profile = Mock()
        profile.component_root_media_id.side_effect = ["root-a", "root-b"]
        profile.select.side_effect = [
            SimpleNamespace(media_ids={"123"}, fingerprint_payload={}),
            SimpleNamespace(media_ids=set(), fingerprint_payload={}),
        ]
        profile.detail_cache_warm_media_ids.return_value = set()
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
        )
        mock_get_profile.return_value = profile

        service.run(
            profile_key="satellites",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        calls = discovery_service.process_snapshot.call_args_list
        self.assertEqual(calls[0].kwargs["component_root_mal_id"], "root-a")
        self.assertEqual(calls[0].kwargs["imported_media_ids"], {"123"})
        self.assertEqual(calls[1].kwargs["component_root_mal_id"], "root-b")
        self.assertEqual(calls[1].kwargs["imported_media_ids"], set())

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_baseline_created_in_run_forces_baseline_on_same_root_seed(
        self,
        mock_get_profile,
    ):
        discovery_service = Mock()
        discovery_service.process_snapshot.side_effect = [
            AnimeFranchiseDiscoveryStats(baseline_created=1),
            AnimeFranchiseDiscoveryStats(),
        ]
        due_seeds = [
            SimpleNamespace(user_id=self.user.id, seed_mal_id="321"),
            SimpleNamespace(user_id=self.user.id, seed_mal_id="654"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            SimpleNamespace(continuity_component=["a"]),
            SimpleNamespace(continuity_component=["b"]),
        ]
        state_service = Mock()
        state_service.select_due_seeds.return_value = (due_seeds, 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)
        profile = Mock()
        profile.component_root_media_id.side_effect = ["root-a", "root-a"]
        profile.select.side_effect = [
            SimpleNamespace(media_ids=set(), fingerprint_payload={}),
            SimpleNamespace(media_ids=set(), fingerprint_payload={}),
        ]
        profile.detail_cache_warm_media_ids.return_value = set()
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
        )
        mock_get_profile.return_value = profile

        service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        calls = discovery_service.process_snapshot.call_args_list
        self.assertFalse(calls[0].kwargs["force_baseline_suppression"])
        self.assertTrue(calls[1].kwargs["force_baseline_suppression"])


class AnimeFranchiseImportLocalSeriesProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="local-series-import-user"
        )

    def _track(self, media_id):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=f"Anime {media_id}",
            image=f"https://example.com/{media_id}.jpg",
        )
        Anime.objects.bulk_create(
            [
                Anime(
                    user=self.user,
                    item=item,
                    status=Status.PLANNING.value,
                )
            ]
        )

    @staticmethod
    def _projection_snapshot(
        *,
        seed_media_id,
        media_ids,
        relations=(),
        canonical_root_media_id=None,
    ):
        nodes = {
            str(media_id): SimpleNamespace(media_id=str(media_id))
            for media_id in media_ids
        }
        return SimpleNamespace(
            root_node=nodes[str(seed_media_id)],
            nodes_by_media_id=nodes,
            all_normalized_relations=list(relations),
            continuity_component=list(nodes.values()),
            series_line=list(nodes.values()),
            direct_anchors=[],
            direct_candidates=[],
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            root_story_parent_candidates=[],
            canonical_root_media_id=str(
                canonical_root_media_id or seed_media_id
            ),
        )

    @staticmethod
    def _relation(source_media_id, target_media_id, relation_type):
        return SimpleNamespace(
            source_media_id=str(source_media_id),
            target_media_id=str(target_media_id),
            relation_type=relation_type,
        )

    def _build_service(
        self,
        *,
        selection_media_ids,
        resolver,
        projection_service,
        seed_media_id="10",
        snapshot=None,
    ):
        due_seed = SimpleNamespace(
            user_id=self.user.id,
            seed_mal_id=str(seed_media_id),
        )
        snapshot = snapshot or SimpleNamespace(
            nodes_by_media_id={"10": object(), "20": object()},
            continuity_component=[
                SimpleNamespace(media_id="10"),
                SimpleNamespace(media_id="20"),
            ],
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot

        state_service = Mock()
        state_service.select_due_seeds.return_value = ([due_seed], 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)

        profile = Mock()
        profile.component_root_media_id.return_value = "10"
        profile.select.return_value = SimpleNamespace(
            media_ids=set(selection_media_ids),
            fingerprint_payload={},
        )
        profile.detail_cache_warm_media_ids.return_value = set()

        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = (
            AnimeFranchiseDiscoveryStats()
        )
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
            local_series_resolver=resolver,
            local_series_projection_service=projection_service,
        )
        return service, profile, state_service, snapshot

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_real_import_resolves_and_persists_local_series_projection(
        self,
        mock_get_profile,
    ):
        self._track("10")
        resolution = LocalSeriesResolution(
            groups=[
                LocalSeriesGroup(
                    root_media_id="10",
                    group_kind="singleton",
                    member_media_ids=["10"],
                )
            ],
            resolver_version="v1",
        )
        resolver = Mock()
        resolver.resolve.return_value = resolution
        projection_service = Mock()
        projection_service.persist.return_value = (
            AnimeLocalSeriesProjectionStats(memberships_recorded=1)
        )
        service, profile, _state_service, snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=projection_service,
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="complete",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        resolver.resolve.assert_called_once_with(snapshot, {"10"})
        projection_service.persist.assert_called_once_with(
            user=self.user,
            resolution=resolution,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
            scope_media_ids={"10", "20"},
        )
        self.assertEqual(stats.local_series_groups_resolved, 1)
        self.assertEqual(stats.local_series_memberships_recorded, 1)
        self.assertEqual(stats.local_series_projection_errors, 0)

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_projection_scope_includes_full_snapshot_component(
        self,
        mock_get_profile,
    ):
        self._track("10")
        self._track("30")
        resolver = Mock()
        resolver.resolve.return_value = LocalSeriesResolution(
            groups=[],
            resolver_version="v1",
        )
        projection_service = Mock()
        projection_service.persist.return_value = (
            AnimeLocalSeriesProjectionStats()
        )
        service, profile, _state_service, snapshot = self._build_service(
            selection_media_ids={"30"},
            resolver=resolver,
            projection_service=projection_service,
        )
        snapshot.nodes_by_media_id = {"10": object()}
        snapshot.continuity_component = [
            SimpleNamespace(media_id="10"),
            SimpleNamespace(media_id="20"),
        ]
        snapshot.all_normalized_relations = [
            SimpleNamespace(
                source_media_id="20",
                target_media_id="40",
            )
        ]
        mock_get_profile.return_value = profile

        service.run(
            profile_key="complete",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            projection_service.persist.call_args.kwargs["scope_media_ids"],
            {"10", "20", "30", "40"},
        )

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_re_zero_satellite_seed_uses_canonical_projection_snapshot(
        self,
        mock_get_profile,
    ):
        tracked_ids = {
            "31240",
            "36286",
            "38414",
            "39587",
            "42203",
            "54857",
            "61316",
        }
        for media_id in tracked_ids:
            self._track(media_id)
        local_snapshot = self._projection_snapshot(
            seed_media_id="36286",
            media_ids={"31240", "36286"},
            relations=[
                self._relation("36286", "31240", "parent_story"),
                self._relation("31240", "36286", "side_story"),
            ],
        )
        canonical_snapshot = self._projection_snapshot(
            seed_media_id="31240",
            media_ids=tracked_ids,
            canonical_root_media_id="31240",
        )
        resolution = LocalSeriesResolution(
            groups=[
                LocalSeriesGroup(
                    root_media_id="38414",
                    group_kind="main_continuity",
                    member_media_ids=[
                        "38414",
                        "31240",
                        "39587",
                        "42203",
                        "54857",
                        "61316",
                        "36286",
                    ],
                )
            ],
            resolver_version="v1",
        )
        resolver = Mock()
        resolver.resolve.return_value = resolution
        projection_service = Mock()
        projection_service.persist.return_value = (
            AnimeLocalSeriesProjectionStats(memberships_recorded=7)
        )
        service, profile, _state_service, _snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=projection_service,
            seed_media_id="36286",
            snapshot=local_snapshot,
        )
        service.snapshot_service.build.side_effect = [
            local_snapshot,
            canonical_snapshot,
        ]
        profile.component_root_media_id.return_value = "36286"
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(
            service.snapshot_service.build.call_args_list,
            [
                call("36286", refresh_cache=False),
                call("31240", refresh_cache=False),
            ],
        )
        resolver.resolve.assert_called_once_with(canonical_snapshot, tracked_ids)
        projection_service.persist.assert_called_once_with(
            user=self.user,
            resolution=resolution,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
            scope_media_ids=tracked_ids,
        )
        self.assertEqual(stats.local_series_memberships_recorded, 7)

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_satellite_import_persists_all_tracked_canonical_memberships(
        self,
        mock_get_profile,
    ):
        tracked_ids = {
            "31240",
            "36286",
            "38414",
            "39587",
            "42203",
            "54857",
            "61316",
        }
        for media_id in tracked_ids:
            self._track(media_id)
        local_snapshot = self._projection_snapshot(
            seed_media_id="36286",
            media_ids={"31240", "36286"},
            relations=[
                self._relation("36286", "31240", "parent_story"),
                self._relation("31240", "36286", "side_story"),
            ],
        )
        canonical_snapshot = self._projection_snapshot(
            seed_media_id="31240",
            media_ids=tracked_ids,
            canonical_root_media_id="31240",
        )
        resolver = Mock()
        resolver.resolve.return_value = LocalSeriesResolution(
            groups=[
                LocalSeriesGroup(
                    root_media_id="38414",
                    group_kind="main_continuity",
                    member_media_ids=sorted(tracked_ids),
                )
            ],
            resolver_version="v1",
        )
        service, profile, _state_service, _snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=AnimeLocalSeriesProjectionService(),
            seed_media_id="36286",
            snapshot=local_snapshot,
        )
        service.snapshot_service.build.side_effect = [
            local_snapshot,
            canonical_snapshot,
        ]
        profile.component_root_media_id.return_value = "36286"
        mock_get_profile.return_value = profile

        service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        memberships = AnimeLocalSeriesMembership.objects.filter(
            user=self.user,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
        )
        self.assertEqual(
            set(memberships.values_list("media_id", flat=True)),
            tracked_ids,
        )
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"38414"},
        )

        service.snapshot_service.build.side_effect = [
            local_snapshot,
            canonical_snapshot,
        ]
        service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        memberships = AnimeLocalSeriesMembership.objects.filter(
            user=self.user,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
        )
        self.assertEqual(memberships.count(), len(tracked_ids))
        self.assertEqual(
            set(memberships.values_list("media_id", flat=True)),
            tracked_ids,
        )
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"38414"},
        )

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_canonical_rebuild_failure_preserves_existing_projection(
        self,
        mock_get_profile,
    ):
        self._track("31240")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="31240",
            root_media_id="38414",
            group_kind="main_continuity",
            component_size=6,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
            resolver_version="v1",
        )
        local_snapshot = self._projection_snapshot(
            seed_media_id="36286",
            media_ids={"31240", "36286"},
            relations=[
                self._relation("36286", "31240", "parent_story"),
            ],
        )
        resolver = Mock()
        projection_service = Mock()
        service, profile, state_service, _snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=projection_service,
            seed_media_id="36286",
            snapshot=local_snapshot,
        )
        service.snapshot_service.build.side_effect = [
            local_snapshot,
            RuntimeError("canonical build failed"),
        ]
        profile.component_root_media_id.return_value = "36286"
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        resolver.resolve.assert_not_called()
        projection_service.persist.assert_not_called()
        self.assertEqual(stats.local_series_projection_errors, 1)
        self.assertEqual(stats.errors, 0)
        state_service.record_success.assert_called_once()
        membership = AnimeLocalSeriesMembership.objects.get(
            user=self.user,
            media_id="31240",
        )
        self.assertEqual(membership.root_media_id, "38414")

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_strong_branch_relations_do_not_promote_canonical_parent(
        self,
        mock_get_profile,
    ):
        for relation_type in (
            "spin_off",
            "alternative_version",
            "alternative_setting",
        ):
            with self.subTest(relation_type=relation_type):
                snapshot = self._projection_snapshot(
                    seed_media_id="20",
                    media_ids={"10", "20"},
                    relations=[
                        self._relation("10", "20", relation_type),
                        self._relation("20", "10", "parent_story"),
                        self._relation("10", "20", "side_story"),
                    ],
                )
                resolver = Mock()
                resolution = LocalSeriesResolution(
                    groups=[],
                    resolver_version="v1",
                )
                resolver.resolve.return_value = resolution
                projection_service = Mock()
                projection_service.persist.return_value = (
                    AnimeLocalSeriesProjectionStats()
                )
                service, profile, _state_service, _snapshot = (
                    self._build_service(
                        selection_media_ids=set(),
                        resolver=resolver,
                        projection_service=projection_service,
                        seed_media_id="20",
                        snapshot=snapshot,
                    )
                )
                profile.component_root_media_id.return_value = "20"
                mock_get_profile.return_value = profile

                service.run(
                    profile_key="satellites",
                    dry_run=False,
                    full_rescan=False,
                    limit=None,
                    refresh_cache=False,
                    user_ids=[self.user.id],
                )

                service.snapshot_service.build.assert_called_once_with(
                    "20",
                    refresh_cache=False,
                )
                resolver.resolve.assert_called_once_with(snapshot, set())

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_satellite_import_selection_remains_independent_from_projection(
        self,
        mock_get_profile,
    ):
        self._track("31240")
        local_snapshot = self._projection_snapshot(
            seed_media_id="36286",
            media_ids={"31240", "36286"},
            relations=[
                self._relation("36286", "31240", "parent_story"),
            ],
        )
        canonical_snapshot = self._projection_snapshot(
            seed_media_id="31240",
            media_ids={"31240", "36286", "38414"},
        )
        resolver = Mock()
        resolver.resolve.return_value = LocalSeriesResolution(
            groups=[],
            resolver_version="v1",
        )
        projection_service = Mock()
        service, profile, _state_service, _snapshot = self._build_service(
            selection_media_ids={"999"},
            resolver=resolver,
            projection_service=projection_service,
            seed_media_id="36286",
            snapshot=local_snapshot,
        )
        service.snapshot_service.build.side_effect = [
            local_snapshot,
            canonical_snapshot,
        ]
        profile.component_root_media_id.return_value = "36286"
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        profile.select.assert_called_once_with(local_snapshot)
        self.assertEqual(stats.planned_creations, 1)
        resolver.resolve.assert_called_once_with(
            canonical_snapshot,
            {"31240", "999"},
        )
        projection_service.persist.assert_not_called()

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_dry_run_resolves_planned_entries_without_persisting(
        self,
        mock_get_profile,
    ):
        self._track("10")
        resolution = LocalSeriesResolution(groups=[], resolver_version="v1")
        resolver = Mock()
        resolver.resolve.return_value = resolution
        projection_service = Mock()
        service, profile, _state_service, snapshot = self._build_service(
            selection_media_ids={"20"},
            resolver=resolver,
            projection_service=projection_service,
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="satellites",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        resolver.resolve.assert_called_once_with(snapshot, {"10", "20"})
        projection_service.persist.assert_not_called()
        profile.select.assert_called_once_with(snapshot)
        self.assertEqual(stats.planned_creations, 1)
        self.assertEqual(stats.created, 0)
        self.assertEqual(stats.already_exists, 0)
        self.assertEqual(stats.local_series_projection_skipped_dry_run, 1)
        self.assertEqual(stats.local_series_memberships_recorded, 0)

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_resolver_error_does_not_fail_import(
        self,
        mock_get_profile,
    ):
        resolver = Mock()
        resolver.resolve.side_effect = RuntimeError("resolver boom")
        projection_service = Mock()
        service, profile, state_service, _snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=projection_service,
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="complete",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.local_series_projection_errors, 1)
        self.assertEqual(stats.errors, 0)
        projection_service.persist.assert_not_called()
        state_service.record_success.assert_called_once()

    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_persistence_error_does_not_fail_import(
        self,
        mock_get_profile,
    ):
        resolver = Mock()
        resolver.resolve.return_value = LocalSeriesResolution(
            groups=[],
            resolver_version="v1",
        )
        projection_service = Mock()
        projection_service.persist.side_effect = RuntimeError("persist boom")
        service, profile, state_service, _snapshot = self._build_service(
            selection_media_ids=set(),
            resolver=resolver,
            projection_service=projection_service,
        )
        mock_get_profile.return_value = profile

        stats = service.run(
            profile_key="complete",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.local_series_projection_errors, 1)
        self.assertEqual(stats.errors, 0)
        state_service.record_success.assert_called_once()
