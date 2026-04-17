from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_franchise_import import AnimeFranchiseImportService


class AnimeFranchiseImportNotificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="import-user")

    def _build_service(self, media_ids):
        snapshot_service = Mock()
        snapshot_service.build.return_value = object()

        state_service = Mock()
        state_service.select_due_seeds.return_value = (
            [SimpleNamespace(user_id=self.user.id, seed_mal_id="321")],
            0,
        )
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (None, True, None)

        profile = Mock()
        profile.select.return_value = SimpleNamespace(
            media_ids=media_ids,
            fingerprint_payload={"key": "value"},
        )
        profile.component_root_media_id.return_value = "321"

        return AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            state_service=state_service,
        ), profile

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_newly_created_anime_schedules_notification(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        service, profile = self._build_service({"123"})
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
        mock_notify.assert_called_once_with(
            user_id=self.user.id,
            media_label=str(created_anime),
        )

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_existing_anime_does_not_schedule_notification(
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

        service, profile = self._build_service({"123"})
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
        mock_notify.assert_not_called()
        mock_anime_minimal.assert_not_called()

    @patch("app.services.anime_franchise_import.notify_entry_added_after_commit")
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_dry_run_does_not_schedule_notification(
        self,
        mock_get_profile,
        mock_anime_minimal,
        mock_notify,
    ):
        service, profile = self._build_service({"123"})
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
        self.assertFalse(Anime.objects.filter(user=self.user, item__media_id="123").exists())
        mock_notify.assert_not_called()
        mock_anime_minimal.assert_not_called()
