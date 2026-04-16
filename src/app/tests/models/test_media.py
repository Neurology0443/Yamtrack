from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Anime,
    AnimeImportScanState,
    Item,
    MediaTypes,
    Sources,
    Status,
)

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


class MediaModel(TestCase):
    """Test the custom save of the Media model."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_anime = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Cowboy Bebop",
            image="http://example.com/image.jpg",
        )

        self.anime = Anime.objects.create(
            item=item_anime,
            user=self.user,
            status=Status.PLANNING.value,
        )

    def test_completed_progress(self):
        """When completed, the progress should be the total number of episodes."""
        self.anime.status = Status.COMPLETED.value
        self.anime.save()
        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).progress,
            26,
        )

    def test_progress_is_max(self):
        """When progress is maximum number of episodes.

        Status should be completed and end_date the current date if not specified.
        """
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.progress = 26
        self.anime.save()

        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).status,
            Status.COMPLETED.value,
        )
        self.assertIsNotNone(
            Anime.objects.get(item__media_id="1", user=self.user).end_date,
        )

    def test_progress_bigger_than_max(self):
        """When progress is bigger than max, it should be set to max."""
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.progress = 30
        self.anime.save()
        self.assertEqual(
            Anime.objects.get(item__media_id="1", user=self.user).progress,
            26,
        )

    @patch("app.services.anime_import_state.AnimeImportStateService.mark_due_now")
    def test_hot_priority_on_manual_mal_anime_add(self, mock_mark_due_now):
        item = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Trigun",
            image="http://example.com/image2.jpg",
        )
        Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        mock_mark_due_now.assert_called_once_with(
            user_id=self.user.id,
            seed_mal_id="2",
        )

    def test_hot_priority_manual_add_creates_due_state_rows(self):
        item = Item.objects.create(
            media_id="20",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Black Lagoon",
            image="http://example.com/image20.jpg",
        )
        Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        states = AnimeImportScanState.objects.filter(
            user=self.user,
            seed_mal_id="20",
        ).order_by("profile_key")
        self.assertEqual(states.count(), 3)
        self.assertEqual(
            list(states.values_list("profile_key", flat=True)),
            ["complete", "continuity", "satellites"],
        )

    @patch("app.services.anime_import_state.AnimeImportStateService.mark_due_now")
    def test_hot_priority_on_in_progress_or_completed_transition(self, mock_mark_due_now):
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.save()
        self.anime.status = Status.COMPLETED.value
        self.anime.save()

        self.assertEqual(mock_mark_due_now.call_count, 2)

    def test_hot_priority_transition_creates_due_state_rows_when_missing(self):
        AnimeImportScanState.objects.all().delete()
        self.anime.status = Status.IN_PROGRESS.value
        self.anime.save()

        self.assertEqual(
            AnimeImportScanState.objects.filter(
                user=self.user,
                seed_mal_id="1",
            ).count(),
            3,
        )

        AnimeImportScanState.objects.all().delete()
        self.anime.status = Status.COMPLETED.value
        self.anime.save()
        self.assertEqual(
            AnimeImportScanState.objects.filter(
                user=self.user,
                seed_mal_id="1",
            ).count(),
            3,
        )

    @patch("app.services.anime_import_state.AnimeImportStateService.mark_due_now")
    def test_hot_priority_not_triggered_for_imported_planning_flag(self, mock_mark_due_now):
        item = Item.objects.create(
            media_id="3",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Ergo Proxy",
            image="http://example.com/image3.jpg",
        )
        anime = Anime(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        anime.save()

        mock_mark_due_now.assert_not_called()

    def test_hot_priority_suppressed_row_does_not_create_scan_state(self):
        item = Item.objects.create(
            media_id="3",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Ergo Proxy",
            image="http://example.com/image3.jpg",
        )
        anime = Anime(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        anime.save()

        self.assertFalse(
            AnimeImportScanState.objects.filter(
                user=self.user,
                seed_mal_id="3",
            ).exists()
        )
