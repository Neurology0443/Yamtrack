# ruff: noqa: D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshStats,
)


class RebuildAnimeSeriesViewCommandTests(TestCase):
    """Test command validation and synchronous service wiring."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-command")

    def test_requires_user_selection_and_rejects_conflicting_selection(self):
        with self.assertRaises(CommandError):
            call_command("rebuild_anime_series_view")
        with self.assertRaises(CommandError):
            call_command(
                "rebuild_anime_series_view",
                "--all-users",
                "--user-id",
                str(self.user.id),
            )

    @patch(
        "app.management.commands.rebuild_anime_series_view."
        "AnimeSeriesViewFranchiseRefreshService"
    )
    def test_uses_tracked_mal_ids_and_forwards_dry_run(self, service_cls):
        item = Item.objects.create(
            media_id="42",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime 42",
            image="https://example.com/42.jpg",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        anime.save()
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(requested=1)
        )

        call_command(
            "rebuild_anime_series_view",
            "--user-id",
            str(self.user.id),
            "--dry-run",
        )

        service_cls.return_value.refresh_for_media_ids.assert_called_once_with(
            user=self.user,
            media_ids=("42",),
            refresh_cache=False,
            dry_run=True,
        )
