# ruff: noqa: D101,D102
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_local_series_refresh import (
    AnimeLocalSeriesProjectionRefreshStats,
)


class RebuildAnimeSeriesViewCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rebuild")
        item = Item.objects.create(
            media_id="100",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime",
            image="image",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            anime.save()

    def test_requires_explicit_user_scope(self):
        with self.assertRaisesMessage(
            CommandError,
            "Use --user-id or --all-users.",
        ):
            call_command("rebuild_anime_series_view")

    @patch(
        "app.management.commands.rebuild_anime_series_view."
        "AnimeLocalSeriesProjectionRefreshService"
    )
    def test_uses_canonical_refresh_service(self, service_class):
        service = Mock()
        service.refresh_for_media_ids.return_value = (
            AnimeLocalSeriesProjectionRefreshStats(
                canonical_roots_refreshed=1,
                memberships_recorded=1,
            )
        )
        service_class.return_value = service

        call_command(
            "rebuild_anime_series_view",
            "--user-id",
            str(self.user.id),
            "--dry-run",
        )

        service.refresh_for_media_ids.assert_called_once_with(
            user=self.user,
            media_ids={"100"},
            refresh_cache=False,
            dry_run=True,
        )
