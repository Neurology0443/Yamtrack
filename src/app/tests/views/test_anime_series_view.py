# ruff: noqa: D101,D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Anime,
    AnimeLocalSeriesMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)


class AnimeSeriesViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="series-view",
        )
        self.client.force_login(self.user)

    def track(self, media_id, title):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=title,
            image="https://example.com/image.jpg",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            anime.save()
        return anime

    @patch(
        "app.services.anime_local_series_refresh."
        "AnimeLocalSeriesProjectionRefreshService.refresh_for_media_ids"
    )
    @patch(
        "app.services.anime_local_series_resolver."
        "AnimeLocalSeriesResolver.resolve"
    )
    @patch(
        "app.services.anime_franchise_snapshot."
        "AnimeFranchiseSnapshotService.build"
    )
    def test_series_view_reads_memberships_only(
        self,
        mock_snapshot_build,
        mock_resolve,
        mock_refresh,
    ):
        first = self.track("100", "Season 1")
        second = self.track("101", "Season 2")
        for anime in (first, second):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=anime.item.media_id,
                root_media_id="100",
                group_kind="main_continuity",
                component_size=2,
                source_profile_key="series_view",
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "app/components/anime_series_groups.html",
        )
        self.assertContains(response, "Season 1")
        self.assertContains(response, "Season 2")
        mock_snapshot_build.assert_not_called()
        mock_resolve.assert_not_called()
        mock_refresh.assert_not_called()

    def test_missing_membership_uses_display_only_singleton(self):
        self.track("100", "Standalone")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Standalone")
        self.assertFalse(AnimeLocalSeriesMembership.objects.exists())

    @patch("app.views._refresh_anime_series_view")
    def test_delete_schedules_refresh_after_commit(self, mock_refresh):
        anime = self.track("100", "Deleted")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("media_delete"),
                {
                    "instance_id": anime.id,
                    "media_type": MediaTypes.ANIME.value,
                },
            )

        self.assertEqual(response.status_code, 302)
        mock_refresh.assert_called_once_with(
            user=self.user,
            media_id="100",
        )

    @patch("app.views._refresh_anime_series_view")
    @patch("app.views.services.get_media_metadata")
    def test_manual_mal_add_schedules_refresh_after_commit(
        self,
        mock_metadata,
        mock_refresh,
    ):
        mock_metadata.return_value = {
            "title": "Added",
            "image": "https://example.com/image.jpg",
            "max_progress": 12,
        }
        with (
            patch.object(Item, "fetch_releases"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                reverse("media_save"),
                {
                    "media_id": "200",
                    "source": Sources.MAL.value,
                    "media_type": MediaTypes.ANIME.value,
                    "status": Status.PLANNING.value,
                    "progress": "0",
                    "score": "",
                    "start_date": "",
                    "end_date": "",
                    "notes": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        mock_refresh.assert_called_once_with(
            user=self.user,
            media_id="200",
        )
