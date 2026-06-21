# ruff: noqa: D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryStats
from app.services.anime_franchise_import import AnimeFranchiseImportService


class AnimeSeriesViewImportIntegrationTests(TestCase):
    """Test one grouped Series View refresh trigger per imported snapshot."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-import")

    def build_service(self, trigger):
        snapshot = SimpleNamespace(continuity_component=["1", "2"])
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        state_service = Mock()
        state_service.select_due_seeds.return_value = (
            [SimpleNamespace(user_id=self.user.id, seed_mal_id="100")],
            0,
        )
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)
        state_service.record_error.return_value = (None, True)
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = AnimeFranchiseDiscoveryStats()
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
            series_view_refresh_trigger=trigger,
        )
        profile = Mock()
        profile.component_root_media_id.return_value = "90"
        profile.select.return_value = SimpleNamespace(
            media_ids={"101", "102"},
            fingerprint_payload={},
        )
        profile.detail_cache_warm_media_ids.return_value = set()
        return service, profile

    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multiple_creations_schedule_one_batch_with_seed_and_root(
        self,
        get_profile,
        anime_minimal,
    ):
        trigger = Mock()
        service, profile = self.build_service(trigger)
        get_profile.return_value = profile
        anime_minimal.side_effect = [
            {"title": "Anime 101", "image": "https://example.com/101.jpg"},
            {"title": "Anime 102", "image": "https://example.com/102.jpg"},
        ]

        stats = service.run(
            profile_key="continuity",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 2)
        trigger.schedule_import_batch.assert_called_once()
        call = trigger.schedule_import_batch.call_args
        self.assertEqual(call.kwargs["user"], self.user)
        self.assertEqual(call.kwargs["media_ids"], {"90", "100", "101", "102"})

    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_dry_run_does_not_schedule_refresh(
        self,
        get_profile,
        anime_minimal,
    ):
        trigger = Mock()
        service, profile = self.build_service(trigger)
        get_profile.return_value = profile

        service.run(
            profile_key="continuity",
            dry_run=True,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        trigger.schedule_import_batch.assert_not_called()
        anime_minimal.assert_not_called()

    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_refresh_enqueue_failure_does_not_break_import(
        self,
        get_profile,
        anime_minimal,
    ):
        trigger = Mock()
        trigger.schedule_import_batch.side_effect = RuntimeError("queue down")
        service, profile = self.build_service(trigger)
        profile.select.return_value = SimpleNamespace(
            media_ids={"101"},
            fingerprint_payload={},
        )
        get_profile.return_value = profile
        anime_minimal.return_value = {
            "title": "Anime 101",
            "image": "https://example.com/101.jpg",
        }

        stats = service.run(
            profile_key="continuity",
            dry_run=False,
            full_rescan=False,
            limit=None,
            refresh_cache=False,
            user_ids=[self.user.id],
        )

        self.assertEqual(stats.created, 1)
        self.assertEqual(stats.errors, 0)
