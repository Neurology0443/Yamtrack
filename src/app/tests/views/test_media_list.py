from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Anime,
    AnimeLocalSeriesMembership,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from app.services.anime_local_series_constants import (
    LOCAL_SERIES_VIEW_PROFILE_KEY,
)
from app.templatetags import app_tags
from users.forms import UserUpdateForm


class MediaListViewTests(TestCase):
    """Test the media list view."""

    def setUp(self):
        """Create a user and log in."""
        self.metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={"max_progress": 1},
        )
        self.metadata_patcher.start()
        self.addCleanup(self.metadata_patcher.stop)
        self.credentials = {"username": "test", "password": "12345"}
        self.external_credentials = {
            "username": "test2",
            "password": "12345",
            "profile_private": True,
        }
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.external_user = get_user_model().objects.create_user(
            **self.external_credentials
        )
        self.client.login(**self.credentials)

        movies_id = ["278", "238", "129", "424", "680"]
        num_completed = 3
        for i in range(1, 6):
            item = Item.objects.create(
                media_id=movies_id[i - 1],
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Test Movie {i}",
                image="http://example.com/image.jpg",
            )
            status = (
                Status.COMPLETED.value
                if i < num_completed
                else Status.IN_PROGRESS.value
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=status,
                progress=1 if i < num_completed else 0,
                score=i,
            )

    def test_media_list_view(self):
        """Test the media list view displays media items."""
        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_list.html")

        self.assertIn("media_list", response.context)
        self.assertEqual(response.context["media_list"].paginator.count, 5)

        self.assertIn("sort_choices", response.context)
        self.assertIn("status_choices", response.context)
        self.assertEqual(response.context["media_type"], MediaTypes.MOVIE.value)
        self.assertEqual(
            response.context["media_type_plural"],
            app_tags.media_type_readable_plural(MediaTypes.MOVIE.value).lower(),
        )

    def test_media_list_with_filters(self):
        """Test the media list view with filters."""
        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value])
            + "?status=Completed&sort=score&layout=table",
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["current_status"],
            Status.COMPLETED.value,
        )
        self.assertEqual(response.context["current_sort"], "score")
        self.assertEqual(response.context["current_layout"], "table")

        self.assertEqual(response.context["media_list"].paginator.count, 2)

        self.user.refresh_from_db()
        self.assertEqual(self.user.movie_status, Status.COMPLETED.value)
        self.assertEqual(self.user.movie_sort, "score")
        self.assertEqual(self.user.movie_layout, "table")

    def test_media_list_htmx_request(self):
        """Test the media list view with HTMX request."""
        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value])
            + "?layout=grid",
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/media_grid_items.html")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value])
            + "?layout=table",
            headers={"hx-request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/media_table_items.html")

    def test_anime_series_layout_groups_from_persisted_projection(self):
        """Series layout uses persisted groups and singleton fallback."""
        root = self._create_anime("10", "Main")
        sequel = self._create_anime("20", "Sequel")
        alternative = self._create_anime("30", "Alternative")
        AnimeLocalSeriesMembership.objects.bulk_create(
            [
                AnimeLocalSeriesMembership(
                    user=self.user,
                    media_id=media_id,
                    root_media_id="10",
                    group_kind="main_continuity",
                    component_size=2,
                    source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
                    resolver_version="v1",
                )
                for media_id in ("10", "20")
            ]
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series&sort=title",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_layout"], "series")
        groups = list(response.context["anime_series_groups"])
        self.assertEqual(len(groups), 2)
        projected_group = next(group for group in groups if group.root_media_id == "10")
        singleton_group = next(group for group in groups if group.root_media_id == "30")
        self.assertEqual(projected_group.entries, [root, sequel])
        self.assertEqual(singleton_group.entries, [alternative])
        self.assertEqual(singleton_group.group_kind, "singleton")
        self.assertContains(response, 'class="anime-series-card', count=2)

    @patch(
        "app.services.anime_franchise_snapshot."
        "AnimeFranchiseSnapshotService.build"
    )
    @patch(
        "app.services.anime_local_series_resolver."
        "AnimeLocalSeriesResolver.resolve"
    )
    @patch("app.views.services.get_media_metadata")
    @patch("app.views.anime_franchise_cache.load_payload_for_media")
    def test_anime_series_layout_renders_branch_context_without_mal_call(
        self,
        mock_load_payload,
        mock_get_metadata,
        mock_resolve,
        mock_build_snapshot,
    ):
        """Series layout renders DB context without MAL or cache reads."""
        parent = self._create_anime("10", "Main")
        branch = self._create_anime("20", "Alternative")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="20",
            root_media_id="20",
            group_kind="alternative_branch",
            context_parent_media_id="10",
            context_relation_type="alternative_version",
            component_size=1,
            source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
            resolver_version="v1",
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alternative Version")
        self.assertContains(response, parent.item.title)
        self.assertContains(response, branch.item.title)
        mock_load_payload.assert_not_called()
        mock_get_metadata.assert_not_called()
        mock_resolve.assert_not_called()
        mock_build_snapshot.assert_not_called()

    def test_anime_series_layout_paginates_groups_not_entries(self):
        """Series pagination counts groups rather than member entries."""
        media_ids = [str(media_id) for media_id in range(100, 135)]
        anime_entries = [
            self._create_anime(media_id, f"Anime {media_id}")
            for media_id in media_ids
        ]
        AnimeLocalSeriesMembership.objects.bulk_create(
            [
                AnimeLocalSeriesMembership(
                    user=self.user,
                    media_id=anime.item.media_id,
                    root_media_id="100",
                    group_kind="main_continuity",
                    component_size=len(anime_entries),
                    source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
                    resolver_version="v1",
                )
                for anime in anime_entries
            ]
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series",
        )

        groups = response.context["anime_series_groups"]
        self.assertEqual(groups.paginator.count, 1)
        self.assertEqual(len(groups.object_list[0].entries), 35)
        self.assertFalse(groups.has_next())
        self.assertContains(response, 'class="anime-series-card', count=1)

    def test_anime_series_layout_reads_only_series_view_projection(self):
        """A newer import-profile membership cannot override the UI projection."""
        main = self._create_anime("10", "KonoSuba")
        sequel = self._create_anime("20", "KonoSuba Season 2")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="20",
            root_media_id="20",
            group_kind="singleton",
            component_size=1,
            source_profile_key="complete",
            resolver_version="v1",
        )
        for media_id in ("10", "20"):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id="10",
                group_kind="main_continuity",
                component_size=2,
                source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
                resolver_version="v1",
            )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series&sort=title",
        )

        groups = list(response.context["anime_series_groups"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].entries, [main, sequel])
        self.assertEqual(groups[0].title, "KonoSuba")
        self.assertContains(response, 'class="anime-series-card', count=1)

    def test_anime_series_layout_renders_spin_off_as_separate_card(self):
        """A persisted spin-off branch appears as its own visible card."""
        main = self._create_anime("10", "KonoSuba")
        spin_off = self._create_anime("20", "KonoSuba: Explosion")
        AnimeLocalSeriesMembership.objects.bulk_create(
            [
                AnimeLocalSeriesMembership(
                    user=self.user,
                    media_id="10",
                    root_media_id="10",
                    group_kind="main_continuity",
                    component_size=1,
                    source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
                    resolver_version="v1",
                ),
                AnimeLocalSeriesMembership(
                    user=self.user,
                    media_id="20",
                    root_media_id="20",
                    group_kind="spin_off_branch",
                    context_parent_media_id="10",
                    context_relation_type="spin_off",
                    component_size=1,
                    source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
                    resolver_version="v1",
                ),
            ]
        )

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series&sort=title",
        )

        groups = list(response.context["anime_series_groups"])
        self.assertEqual(
            [group.title for group in groups],
            [main.item.title, spin_off.item.title],
        )
        self.assertContains(response, 'class="anime-series-card', count=2)

    def test_anime_series_layout_second_page_contains_next_group(self):
        """Series pagination advances one page of groups at a time."""
        for media_id in range(100, 133):
            self._create_anime(str(media_id), f"Anime {media_id}")

        first_page = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series&sort=title",
        )
        second_page = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series&sort=title&page=2",
            headers={"hx-request": "true"},
        )

        self.assertEqual(
            len(first_page.context["anime_series_groups"].object_list),
            32,
        )
        self.assertTrue(first_page.context["anime_series_groups"].has_next())
        self.assertEqual(
            len(second_page.context["anime_series_groups"].object_list),
            1,
        )
        self.assertTemplateUsed(
            second_page,
            "app/components/anime_series_groups.html",
        )

    def test_anime_series_layout_htmx_returns_group_partial(self):
        """HTMX requests render only the series group partial."""
        self._create_anime("10", "Main")

        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.ANIME.value])
            + "?layout=series",
            headers={"hx-request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "app/components/anime_series_groups.html",
        )

    def test_series_layout_is_rejected_for_non_anime_lists(self):
        """The series preference is unavailable to non-anime media."""
        response = self.client.get(
            reverse("medialist", args=[self.user.username, MediaTypes.MOVIE.value])
            + "?layout=series",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_layout"], self.user.movie_layout)

    def _create_anime(self, media_id, title):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=title,
            image="http://example.com/anime.jpg",
        )
        return Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

    def test_public_media_list_ignores_invalid_filters(self):
        """Test invalid public filters fall back to the target user's preferences."""
        self.external_user.profile_private = False
        self.external_user.save(update_fields=["profile_private"])

        response = self.client.get(
            reverse(
                "medialist", args=[self.external_user.username, MediaTypes.MOVIE.value]
            )
            + "?status=invalid&sort=bad_field&layout=invalid",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["current_status"], self.external_user.movie_status
        )
        self.assertEqual(
            response.context["current_sort"], self.external_user.movie_sort
        )
        self.assertEqual(
            response.context["current_layout"], self.external_user.movie_layout
        )

    def test_anonymous_user_can_view_public_media_list(self):
        """Test anonymous users can view public media lists."""
        self.external_user.profile_private = False
        self.external_user.save(update_fields=["profile_private"])
        self.client.logout()

        response = self.client.get(
            reverse(
                "medialist", args=[self.external_user.username, MediaTypes.MOVIE.value]
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("media_list", response.context)

    def test_profile_private_defaults_to_true(self):
        """Test new users have private profiles by default."""
        user = get_user_model().objects.create_user(
            username="private-default",
        )

        self.assertTrue(user.profile_private)

    def test_private_media_list(self):
        """Test the private media list view."""
        response = self.client.get(
            reverse(
                "medialist", args=[self.external_user.username, MediaTypes.MOVIE.value]
            )
        )
        self.assertEqual(response.status_code, 404)

        form = UserUpdateForm(
            data={"username": "test2", "profile_private": False},
            instance=self.external_user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        external_user = form.save()
        external_user.refresh_from_db()

        response = self.client.get(
            reverse(
                "medialist", args=[self.external_user.username, MediaTypes.MOVIE.value]
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("media_list", response.context)
