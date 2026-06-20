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
        self.assertNotContains(response, "Season 2")
        group = response.context["media_list"].object_list[0]
        self.assertEqual(len(group.entries), 2)
        self.assertEqual(group.display_entry.item.media_id, "100")
        mock_snapshot_build.assert_not_called()
        mock_resolve.assert_not_called()
        mock_refresh.assert_not_called()

    def test_series_view_card_hides_grid_hover_actions(self):
        self.track("100", "Series Card")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, 'data-anime-series-card="true"')
        self.assertNotContains(response, 'title="Add to tracker"')
        self.assertNotContains(response, 'title="Add to custom lists"')
        self.assertNotContains(response, 'title="View your activity history"')

    def test_grid_view_keeps_standard_hover_actions(self):
        self.track("100", "Grid Card")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "grid"},
        )

        self.assertNotContains(response, 'data-anime-series-card="true"')
        self.assertContains(response, 'title="Add to tracker"')
        self.assertContains(response, 'title="Add to custom lists"')
        self.assertContains(response, 'title="View your activity history"')

    def test_series_card_overlay_allows_three_title_lines(self):
        self.track(
            "100",
            "A deliberately long anime franchise title for the hover overlay",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, 'data-anime-series-overlay="true"')
        self.assertContains(response, "line-clamp-3")
        self.assertContains(response, "hover:opacity-100")

    def test_series_card_does_not_show_group_title_count(self):
        first = self.track("100", "First")
        second = self.track("101", "Second")
        for anime in (first, second):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=anime.item.media_id,
                root_media_id="100",
                display_media_id="100",
                group_kind="main_continuity",
                source_profile_key="series_view",
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertNotContains(response, "2 titles")

    def test_missing_membership_uses_display_only_singleton(self):
        self.track("100", "Standalone")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Standalone")
        self.assertFalse(AnimeLocalSeriesMembership.objects.exists())

    def test_series_view_renders_only_persisted_display_entry(self):
        main = self.track("31240", "Re:Zero Main")
        prequel = self.track("38414", "Re:Zero Movie")
        for anime in (main, prequel):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=anime.item.media_id,
                root_media_id="38414",
                display_media_id="31240",
                group_kind="main_continuity",
                component_size=2,
                source_profile_key="series_view",
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, "Re:Zero Main")
        self.assertNotContains(response, "Re:Zero Movie")
        group = response.context["media_list"].object_list[0]
        self.assertEqual(group.root_media_id, "38414")
        self.assertEqual(group.display_media_id, "31240")
        self.assertEqual(group.display_entry.item.media_id, "31240")

    def test_blank_display_media_falls_back_to_root_entry(self):
        main = self.track("100", "Root Entry")
        sequel = self.track("101", "Sequel Entry")
        for anime in (main, sequel):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=anime.item.media_id,
                root_media_id="100",
                display_media_id="",
                group_kind="main_continuity",
                component_size=2,
                source_profile_key="series_view",
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        group = response.context["media_list"].object_list[0]
        self.assertEqual(group.display_entry.item.media_id, "100")
        self.assertContains(response, "Root Entry")
        self.assertNotContains(response, "Sequel Entry")

    def test_spin_off_card_shows_local_parent_title(self):
        parent = self.track("100", "Parent Franchise")
        spin_off = self.track("200", "Spin-off Series")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id=parent.item.media_id,
            root_media_id="100",
            display_media_id="100",
            group_kind="singleton",
            source_profile_key="series_view",
            resolver_version="v1",
        )
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id=spin_off.item.media_id,
            root_media_id="200",
            display_media_id="200",
            group_kind="spin_off",
            context_parent_media_id="100",
            context_relation_type="spin_off",
            source_profile_key="series_view",
            resolver_version="v1",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, "Spin Off • Parent Franchise")

    def test_alternative_cards_use_supported_labels(self):
        alternative_version = self.track("200", "Alternative Version Entry")
        alternative_setting = self.track("300", "Alternative Setting Entry")
        for anime, relation_type in (
            (alternative_version, "alternative_version"),
            (alternative_setting, "alternative_setting"),
        ):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=anime.item.media_id,
                root_media_id=anime.item.media_id,
                display_media_id=anime.item.media_id,
                group_kind="alternative_branch",
                context_parent_media_id="100",
                context_relation_type=relation_type,
                source_profile_key="series_view",
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, "Alternative Version")
        self.assertContains(response, "Alternative Setting")

    def test_main_continuity_does_not_show_prequel_or_sequel_label(self):
        main = self.track("100", "Main Continuity")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id=main.item.media_id,
            root_media_id="100",
            display_media_id="100",
            group_kind="main_continuity",
            context_parent_media_id="99",
            context_relation_type="prequel",
            source_profile_key="series_view",
            resolver_version="v1",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertNotContains(response, "Prequel")
        self.assertNotContains(response, "Sequel")

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
