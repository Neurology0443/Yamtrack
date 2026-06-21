# ruff: noqa: D102,S106
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Anime,
    AnimeSeriesViewMembership,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)


class AnimeSeriesViewTests(TestCase):
    """Test media-list integration, partials, fallback, and card pagination."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="series-view",
            password="password",
        )
        self.client.login(username="series-view", password="password")

    def create_anime(self, media_id, root_id=None, *, title=None, root_title=None):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=title or f"Anime {media_id}",
            image=f"https://example.com/{media_id}.jpg",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        anime.save()
        if root_id is not None:
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=str(media_id),
                root_media_id=str(root_id),
                display_media_id=str(root_id),
                display_title=root_title or f"Root {root_id}",
                display_image=f"https://example.com/root-{root_id}.jpg",
                display_media_type="tv",
            )
        return anime

    def test_series_layout_groups_cards_and_reports_unprojected(self):
        self.create_anime("1", root_id="1")
        self.create_anime("2", root_id="1")
        self.create_anime("3")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value]),
            {"layout": "series"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_anime_series_view"])
        self.assertEqual(response.context["media_list"].paginator.count, 1)
        self.assertEqual(response.context["unprojected_count"], 1)
        self.assertContains(
            response,
            "Some anime are still being prepared for Series View.",
        )

    def test_series_card_shows_only_root_metadata_and_links_to_root(self):
        self.create_anime(
            "1",
            root_id="1",
            title="Dragon Ball",
            root_title="Dragon Ball",
        )
        self.create_anime(
            "2",
            root_id="1",
            title="Dragon Ball Z",
            root_title="Dragon Ball",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value]),
            {"layout": "series"},
        )

        root_url = reverse(
            "media_details",
            kwargs={
                "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value,
                "media_id": "1",
                "title": "dragon-ball",
            },
        )
        self.assertContains(response, "Dragon Ball")
        self.assertNotContains(response, "Dragon Ball Z")
        self.assertContains(response, "2 tracked entries")
        self.assertContains(response, f'href="{root_url}"')
        self.assertNotContains(response, "divide-y divide-gray-700/60")

    def test_anime_series_view_empty_state_matches_default_media_list(self):
        url = reverse(
            "medialist",
            args=[self.user.username, MediaTypes.ANIME.value],
        )

        grid_response = self.client.get(url, {"layout": "grid"})
        series_response = self.client.get(url, {"layout": "series"})
        partial_response = self.client.get(
            url,
            {"layout": "series"},
            headers={"hx-request": "true"},
        )

        expected = "No Anime Tracked Yet"
        self.assertContains(grid_response, expected)
        self.assertContains(series_response, expected)
        self.assertContains(partial_response, expected)
        self.assertNotContains(
            series_response,
            "No anime match the current filters.",
        )
        self.assertNotContains(
            partial_response,
            "No anime match the current filters.",
        )
        self.assertTemplateUsed(
            partial_response,
            "app/components/media_list_empty_state.html",
        )

    def test_series_htmx_uses_series_partial(self):
        self.create_anime("1", root_id="1")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value]),
            {"layout": "series"},
            headers={"hx-request": "true"},
        )

        self.assertTemplateUsed(
            response,
            "app/components/anime_series_groups.html",
        )

    def test_non_anime_series_layout_falls_back_to_grid(self):
        item = Item.objects.create(
            media_id="movie",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="https://example.com/movie.jpg",
        )
        movie = Movie(user=self.user, item=item, status=Status.PLANNING.value)
        movie.save()

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value]),
            {"layout": "series"},
        )

        self.assertFalse(response.context["is_anime_series_view"])
        self.assertEqual(response.context["current_layout"], "grid")
        self.user.refresh_from_db()
        self.assertEqual(self.user.movie_layout, "grid")

    @patch("app.views.AnimeSeriesViewRefreshTriggerService")
    def test_delete_mal_anime_schedules_series_view_cleanup(self, trigger_service):
        anime = self.create_anime("779")

        self.client.post(
            reverse("media_delete"),
            data={
                "instance_id": anime.id,
                "media_type": MediaTypes.ANIME.value,
            },
        )

        trigger_service.return_value.schedule_delete.assert_called_once_with(
            user=self.user,
            media_id="779",
        )
