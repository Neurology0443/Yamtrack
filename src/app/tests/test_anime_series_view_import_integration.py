# ruff: noqa: D101, D102

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryStats
from app.services.anime_franchise_import import AnimeFranchiseImportService


class AnimeSeriesViewImportIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="batch-import")
        item = Item.objects.create(
            media_id="321",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Seed",
            image="https://example.com/seed.jpg",
        )
        seed = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        seed._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            seed.save()

    @patch(
        "app.signals.AnimeSeriesViewRefreshTriggerService.schedule_import_batch"
    )
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multi_entry_import_triggers_one_coherent_series_refresh(
        self,
        get_profile,
        anime_minimal,
        schedule_import_batch,
    ):
        snapshot = SimpleNamespace(
            continuity_component=[object(), object(), object()],
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        profile = Mock()
        profile.is_seed_eligible.return_value = True
        profile.component_root_media_id.return_value = "321"
        profile.select.return_value = SimpleNamespace(
            media_ids={"123", "124"},
            fingerprint_payload={"selected": ["123", "124"]},
        )
        profile.detail_cache_warm_media_ids.return_value = set()
        get_profile.return_value = profile
        anime_minimal.side_effect = [
            {
                "title": "Imported 123",
                "image": "https://example.com/123.jpg",
            },
            {
                "title": "Imported 124",
                "image": "https://example.com/124.jpg",
            },
        ]
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = (
            AnimeFranchiseDiscoveryStats()
        )
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
        )

        with patch.object(Item, "fetch_releases"):
            stats = service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=True,
                limit=1,
                refresh_cache=False,
                user_ids=[self.user.id],
            )

        self.assertEqual(stats.created, 2)
        schedule_import_batch.assert_called_once_with(
            user=self.user,
            seed_media_id="321",
            component_root_media_id="321",
        )
