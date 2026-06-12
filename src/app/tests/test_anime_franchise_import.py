# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_franchise_import import AnimeFranchiseImportService


class AnimeFranchiseImportNotificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="import-user")

    def _build_service(
        self,
        media_ids,
        *,
        due_seeds=None,
        root_ids=None,
        selections=None,
        cache_warm_scheduler=None,
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

        return AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=cache_warm_scheduler,
        ), profile

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_newly_created_anime_schedules_notification_and_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        cache_warm_scheduler = Mock(return_value=True)
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
        self.assertEqual(stats.cache_warm_roots, ["321"])
        self.assertEqual(stats.cache_warm_errors, 0)
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

        cache_warm_scheduler = Mock(return_value=True)
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
        cache_warm_scheduler = Mock(return_value=True)
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
        cache_warm_scheduler.assert_called_once_with("321")

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multiple_due_seeds_for_same_root_schedule_single_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock(return_value=True)
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
        cache_warm_scheduler = Mock(return_value=True)
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
        cache_warm_scheduler = Mock(return_value=True)
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
        self.assertEqual(stats.cache_warm_roots, [])
        self.assertFalse(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )
        cache_warm_scheduler.assert_not_called()
        mock_notify.assert_not_called()
        mock_anime_minimal.assert_not_called()


    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_scheduler_false_return_does_not_break_import(
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
        self.assertEqual(stats.cache_warm_errors, 1)
        self.assertEqual(stats.cache_warm_scheduled, 0)
        self.assertEqual(stats.cache_warm_roots, [])
        cache_warm_scheduler.assert_called_once_with("321")
        self.assertTrue(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_partial_error_after_creation_still_schedules_cache_warm(
        self,
        mock_get_profile,
        mock_anime_minimal,
        _mock_notify,
    ):
        cache_warm_scheduler = Mock(return_value=True)
        service, profile = self._build_service(
            {"123", "124"}, cache_warm_scheduler=cache_warm_scheduler
        )
        mock_get_profile.return_value = profile
        mock_anime_minimal.side_effect = [
            {"title": "Anime 123", "image": "http://example.com/123.jpg"},
            RuntimeError("boom"),
        ]

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
        self.assertEqual(stats.cache_warm_roots, [])
        self.assertTrue(
            Anime.objects.filter(user=self.user, item__media_id="123").exists()
        )
