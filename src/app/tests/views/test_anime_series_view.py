# ruff: noqa: D101, D102

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Anime,
    AnimeSeriesViewMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)


class AnimeSeriesViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-view")
        self.client.force_login(self.user)

    def track(self, media_id, title, *, image=None):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=title,
            image=image or "https://example.com/image.jpg",
        )
        anime = Anime(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            anime.save()
        return anime

    def membership(
        self,
        media_id,
        *,
        root="1",
        display="1",
        relation=None,
        parent=None,
    ):
        return AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=str(media_id),
            root_media_id=str(root),
            display_media_id=str(display),
            group_kind="alternative_branch" if relation else "main_continuity",
            context_parent_media_id=parent,
            context_relation_type=relation,
            component_size=2,
            projection_version="v1",
            source_profile_key="series_view",
        )

    @patch(
        "app.services.anime_franchise_snapshot.AnimeFranchiseSnapshotService.build"
    )
    @patch("app.providers.mal.anime")
    def test_view_reads_only_persisted_projection(self, mal_anime, snapshot_build):
        self.track("1", "Season 1")
        self.track("2", "Season 2")
        self.membership("1")
        self.membership("2")

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
        snapshot_build.assert_not_called()
        mal_anime.assert_not_called()

    def test_missing_membership_falls_back_to_singleton(self):
        self.track("1", "Standalone")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Standalone")
        self.assertEqual(response.context["media_list"].paginator.count, 1)

    def test_group_card_uses_display_title_and_branch_subtitle(self):
        self.track("1", "Sword Art Online")
        self.track("2", "Sword Art Online Progressive")
        self.membership(
            "2",
            root="2",
            display="2",
            relation="alternative_version",
            parent="1",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertContains(response, "Sword Art Online Progressive")
        self.assertContains(
            response,
            "Alternative Version • Sword Art Online",
        )

    def test_prequel_and_sequel_are_not_rendered_as_branch_labels(self):
        self.track("1", "Season 1")
        self.membership("1", relation="prequel", parent="2")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, "anime"]),
            {"layout": "series"},
        )

        self.assertNotContains(response, "Prequel")
        self.assertNotContains(response, "Sequel")

    @patch(
        "app.views.AnimeSeriesViewRefreshTriggerService.schedule_manual_add"
    )
    @patch("app.views.services.get_media_metadata")
    def test_manual_mal_add_schedules_refresh_after_save(
        self,
        metadata,
        schedule_refresh,
    ):
        metadata.return_value = {
            "title": "Added",
            "image": "https://example.com/added.jpg",
            "max_progress": 12,
        }

        with patch.object(Item, "fetch_releases"):
            response = self.client.post(
                reverse("media_save"),
                {
                    "media_id": "20",
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
        schedule_refresh.assert_called_once_with(
            user=self.user,
            media_id="20",
        )

    @patch("app.views.AnimeSeriesViewRefreshTriggerService.schedule_delete")
    def test_delete_schedules_refresh_after_delete(self, schedule_refresh):
        anime = self.track("20", "Deleted")

        response = self.client.post(
            reverse("media_delete"),
            {
                "instance_id": anime.id,
                "media_type": MediaTypes.ANIME.value,
            },
        )

        self.assertEqual(response.status_code, 302)
        schedule_refresh.assert_called_once_with(
            user=self.user,
            media_id="20",
        )
