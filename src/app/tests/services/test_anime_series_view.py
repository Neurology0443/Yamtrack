# ruff: noqa: D102
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.anime_series_view_constants import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
)
from app.models import (
    Anime,
    AnimeSeriesViewMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_series_view import build_anime_series_view


class AnimeSeriesViewReadTests(TestCase):
    """Test pure DB grouping and absent-membership behavior."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-reader")

    def create_anime(self, media_id):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=f"Anime {media_id}",
            image=f"https://example.com/{media_id}.jpg",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        anime.save()
        return anime

    def create_membership(self, media_id, root_id, group_kind):
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=str(media_id),
            root_media_id=str(root_id),
            display_media_id=str(root_id),
            display_title=f"Root {root_id}",
            display_image=f"https://example.com/root-{root_id}.jpg",
            display_media_type="tv",
            group_kind=group_kind,
        )

    def test_groups_in_input_order_and_does_not_fallback_for_unprojected(self):
        entries = [self.create_anime(media_id) for media_id in ("2", "1", "3", "4")]
        self.create_membership("2", "10", GROUP_KIND_FRANCHISE)
        self.create_membership("1", "10", GROUP_KIND_FRANCHISE)
        self.create_membership("3", "3", GROUP_KIND_SINGLETON)

        result = build_anime_series_view(
            media_entries=entries,
            user_id=self.user.id,
        )

        self.assertEqual([group.root_media_id for group in result.groups], ["10", "3"])
        self.assertEqual(
            [entry.media_id for entry in result.groups[0].entries],
            ["2", "1"],
        )
        self.assertEqual(result.groups[1].group_kind, GROUP_KIND_SINGLETON)
        self.assertEqual(result.unprojected_count, 1)

    def test_legacy_projection_version_is_used_as_temporary_fallback(self):
        entry = self.create_anime("5")
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id="5",
            root_media_id="5",
            display_media_id="5",
            display_title="Legacy",
            projection_version="franchise_root_v1",
        )

        result = build_anime_series_view(
            media_entries=[entry],
            user_id=self.user.id,
        )

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].root_media_id, "5")
        self.assertEqual(result.unprojected_count, 0)

    def test_v2_display_metadata_wins_over_v1_fallback_for_same_root(self):
        legacy_entry = self.create_anime("6")
        current_entry = self.create_anime("7")
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id="6",
            root_media_id="100",
            display_media_id="100",
            display_title="Old v1",
            display_image="https://example.com/old.jpg",
            display_media_type="tv",
            group_kind=GROUP_KIND_FRANCHISE,
            projection_version="franchise_root_v1",
        )
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id="7",
            root_media_id="100",
            display_media_id="101",
            display_title="Fresh v2",
            display_image="https://example.com/fresh.jpg",
            display_media_type="ona",
            group_kind=GROUP_KIND_FRANCHISE,
            projection_version=PROJECTION_VERSION,
        )

        result = build_anime_series_view(
            media_entries=[legacy_entry, current_entry],
            user_id=self.user.id,
        )

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].display_title, "Fresh v2")
        self.assertEqual(result.groups[0].display_media_id, "101")
        self.assertEqual(
            result.groups[0].display_projection_version,
            PROJECTION_VERSION,
        )
