# ruff: noqa: D101,D102,S106
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from app import helpers
from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services import item_image_sync
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceService
from app.tasks import refresh_mal_anime_metadata


class ItemImageSyncRuleTests(TestCase):
    def test_ignores_empty_and_placeholder_images(self):
        item = Item(
            source=Sources.MAL.value, media_type=MediaTypes.ANIME.value, image=""
        )

        self.assertFalse(item_image_sync.should_sync_provider_image(item, ""))
        self.assertFalse(item_image_sync.should_sync_provider_image(item, None))
        self.assertFalse(
            item_image_sync.should_sync_provider_image(item, settings.IMG_NONE)
        )

    def test_fills_missing_and_placeholder_item_images(self):
        image = "https://cdn.example.test/new.jpg"
        missing = Item(
            source=Sources.TMDB.value, media_type=MediaTypes.MOVIE.value, image=""
        )
        placeholder = Item(
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            image=settings.IMG_NONE,
        )

        self.assertTrue(
            item_image_sync.sync_existing_item_image(missing, image, save=False)
        )
        self.assertTrue(
            item_image_sync.sync_existing_item_image(placeholder, image, save=False)
        )
        self.assertEqual(missing.image, image)
        self.assertEqual(placeholder.image, image)

    def test_mal_replaces_existing_different_image_but_skips_identical(self):
        item = Item(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            image="https://cdn.example.test/old.jpg",
        )

        self.assertTrue(
            item_image_sync.should_sync_provider_image(
                item, "https://cdn.example.test/new.jpg"
            )
        )
        self.assertFalse(
            item_image_sync.should_sync_provider_image(
                item, "https://cdn.example.test/old.jpg"
            )
        )

    def test_non_mal_provider_does_not_replace_existing_different_image(self):
        item = Item(
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            image="https://cdn.example.test/old.jpg",
        )

        self.assertFalse(
            item_image_sync.should_sync_provider_image(
                item, "https://cdn.example.test/new.jpg"
            )
        )

    def test_save_false_mutates_without_saving(self):
        item = Item(
            source=Sources.MAL.value, media_type=MediaTypes.ANIME.value, image=""
        )
        item.save = MagicMock()

        changed = item_image_sync.sync_existing_item_image(
            item, "https://cdn.example.test/new.jpg", save=False
        )

        self.assertTrue(changed)
        self.assertEqual(item.image, "https://cdn.example.test/new.jpg")
        item.save.assert_not_called()


class ItemImageSyncDatabaseTests(TestCase):
    def test_sync_provider_image_filters_to_global_no_season_no_episode_row(self):
        global_item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Global",
            image="old",
        )
        season_item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Season",
            image="old-season",
            season_number=1,
        )

        count = item_image_sync.sync_provider_image(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            media_id=1,
            image="https://cdn.example.test/new.jpg",
        )

        self.assertEqual(count, 1)
        global_item.refresh_from_db()
        season_item.refresh_from_db()
        self.assertEqual(global_item.image, "https://cdn.example.test/new.jpg")
        self.assertEqual(season_item.image, "old-season")

    def test_sync_provider_images_deduplicates_and_last_different_entry_wins(self):
        item = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime",
            image="old",
        )
        entries = [
            item_image_sync.ProviderImageEntry(
                Sources.MAL.value, MediaTypes.ANIME.value, "2", "same"
            ),
            item_image_sync.ProviderImageEntry(
                Sources.MAL.value, MediaTypes.ANIME.value, "2", "same"
            ),
            item_image_sync.ProviderImageEntry(
                Sources.MAL.value, MediaTypes.ANIME.value, "2", "last"
            ),
        ]

        self.assertEqual(item_image_sync.sync_provider_images(entries), 1)
        item.refresh_from_db()
        self.assertEqual(item.image, "last")

    def test_sync_provider_images_updates_global_item_row_used_by_references(self):
        user1 = get_user_model().objects.create_user(username="u1", password="x")
        user2 = get_user_model().objects.create_user(username="u2", password="x")
        item = Item.objects.create(
            media_id="3",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Shared Anime",
            image="old",
        )
        Anime.objects.create(user=user1, item=item, status=Status.PLANNING.value)
        Anime.objects.create(user=user2, item=item, status=Status.PLANNING.value)

        count = item_image_sync.sync_provider_images(
            [
                item_image_sync.ProviderImageEntry(
                    Sources.MAL.value, MediaTypes.ANIME.value, "3", "new"
                )
            ]
        )

        self.assertEqual(count, 1)
        item.refresh_from_db()
        self.assertEqual(item.image, "new")


class ItemImageSyncIntegrationTests(TestCase):
    def test_refresh_item_image_if_missing_uses_centralized_behavior(self):
        item = Item.objects.create(
            media_id="10",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime",
            image="old",
        )

        self.assertTrue(helpers.refresh_item_image_if_missing(item, "new"))
        item.refresh_from_db()
        self.assertEqual(item.image, "new")

    def test_enrich_items_with_user_data_uses_centralized_rule_and_bulk_update(self):
        user = get_user_model().objects.create_user(username="u", password="x")
        request = SimpleNamespace(user=user)
        item = Item.objects.create(
            media_id="11",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime",
            image="old",
        )
        Anime.objects.create(user=user, item=item, status=Status.PLANNING.value)

        with patch(
            "app.helpers.Item.objects.bulk_update", wraps=Item.objects.bulk_update
        ) as bulk_update:
            helpers.enrich_items_with_user_data(
                request,
                [
                    {
                        "media_id": "11",
                        "source": Sources.MAL.value,
                        "media_type": MediaTypes.ANIME.value,
                        "title": "Anime",
                        "image": "new",
                    }
                ],
                "section",
            )

        item.refresh_from_db()
        self.assertEqual(item.image, "new")
        bulk_update.assert_called_once()

    @patch("app.tasks.item_image_sync.sync_provider_image")
    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_calls_image_sync_after_success(
        self, mock_anime, mock_sync
    ):
        mock_anime.return_value = {"image": "new"}

        result = refresh_mal_anime_metadata("12")

        self.assertTrue(result["refreshed"])
        mock_sync.assert_called_once_with(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            media_id="12",
            image="new",
        )

    @patch(
        "app.tasks.item_image_sync.sync_provider_image",
        side_effect=RuntimeError("sync failed"),
    )
    @patch("app.tasks.mal.anime")
    def test_refresh_mal_anime_metadata_image_sync_failure_is_non_fatal(
        self, mock_anime, _mock_sync
    ):
        mock_anime.return_value = {"image": "new"}

        result = refresh_mal_anime_metadata("13")

        self.assertTrue(result["refreshed"])

    def _maintenance_service(self, snapshot):
        discovery_service = MagicMock()
        discovery_service.build_snapshot_fingerprint.return_value = "fingerprint"
        service = AnimeFranchiseMaintenanceService(
            discovery_service=discovery_service,
            cache_build_service_factory=lambda _session: MagicMock(
                build_and_save_from_snapshot=MagicMock(return_value={"built": True})
            ),
        )
        return service, snapshot

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    @patch(
        "app.services.anime_franchise_maintenance.item_image_sync.sync_provider_images"
    )
    def test_maintenance_calls_bulk_image_sync_when_refresh_cache_true(
        self, mock_sync, mock_session
    ):
        user = get_user_model().objects.create_user(username="maint1", password="x")
        node = SimpleNamespace(media_id="21", image="img")
        snapshot = SimpleNamespace(
            canonical_root_media_id="21", nodes_by_media_id={"21": node}
        )
        mock_session.return_value.snapshot_service.return_value.build.return_value = (
            snapshot
        )
        service, _ = self._maintenance_service(snapshot)

        service.process_seed(
            user=user,
            seed_mal_id="21",
            refresh_cache=True,
            update_ui_cache=False,
            process_discovery=False,
        )

        mock_sync.assert_called_once()

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    @patch(
        "app.services.anime_franchise_maintenance.item_image_sync.sync_provider_images"
    )
    def test_maintenance_skips_bulk_image_sync_when_refresh_cache_false(
        self, mock_sync, mock_session
    ):
        user = get_user_model().objects.create_user(username="maint2", password="x")
        snapshot = SimpleNamespace(canonical_root_media_id="22", nodes_by_media_id={})
        mock_session.return_value.snapshot_service.return_value.build.return_value = (
            snapshot
        )
        service, _ = self._maintenance_service(snapshot)

        service.process_seed(
            user=user,
            seed_mal_id="22",
            refresh_cache=False,
            update_ui_cache=False,
            process_discovery=False,
        )

        mock_sync.assert_not_called()

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    @patch(
        "app.services.anime_franchise_maintenance.item_image_sync.sync_provider_images",
        side_effect=RuntimeError("sync failed"),
    )
    def test_maintenance_image_sync_failure_is_non_critical(
        self, _mock_sync, mock_session
    ):
        user = get_user_model().objects.create_user(username="maint3", password="x")
        snapshot = SimpleNamespace(canonical_root_media_id="23", nodes_by_media_id={})
        mock_session.return_value.snapshot_service.return_value.build.return_value = (
            snapshot
        )
        service, _ = self._maintenance_service(snapshot)

        result = service.process_seed(
            user=user,
            seed_mal_id="23",
            refresh_cache=True,
            update_ui_cache=False,
            process_discovery=False,
        )

        self.assertFalse(result.critical_errors)
        self.assertTrue(result.non_critical_errors)
