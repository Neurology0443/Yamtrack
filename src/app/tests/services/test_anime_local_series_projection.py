# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Anime,
    AnimeLocalSeriesMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_local_series_projection import (
    AnimeLocalSeriesProjectionService,
)
from app.services.anime_local_series_resolver import (
    AnimeLocalSeriesGroup,
    AnimeLocalSeriesResolution,
)


class AnimeLocalSeriesProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="projection")
        for media_id in ("100", "101"):
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=media_id,
                image="image",
            )
            anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
            anime._skip_hot_priority = True
            with patch.object(Item, "fetch_releases"):
                anime.save()

    def test_version_bump_replaces_old_scope(self):
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="100",
            root_media_id="100",
            group_kind="singleton",
            source_profile_key="series_view",
            resolver_version="v1",
        )
        resolution = AnimeLocalSeriesResolution(
            groups=(
                AnimeLocalSeriesGroup(
                    root_media_id="100",
                    group_kind="main_continuity",
                    member_media_ids=("100", "101"),
                ),
            ),
            resolver_version="v2",
        )

        stats = AnimeLocalSeriesProjectionService().persist(
            user=self.user,
            source_profile_key="series_view",
            resolver_version="v2",
            resolution=resolution,
            scope_media_ids={"100", "101"},
        )

        self.assertEqual(stats.memberships_deleted, 1)
        self.assertFalse(
            AnimeLocalSeriesMembership.objects.filter(
                resolver_version="v1"
            ).exists()
        )
        self.assertEqual(
            AnimeLocalSeriesMembership.objects.filter(
                resolver_version="v2"
            ).count(),
            2,
        )
    def test_update_preserves_discovered_at(self):
        existing = AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="100",
            root_media_id="100",
            group_kind="singleton",
            source_profile_key="series_view",
            resolver_version="v1",
        )
        discovered_at = existing.discovered_at
        resolution = AnimeLocalSeriesResolution(
            groups=(
                AnimeLocalSeriesGroup(
                    root_media_id="100",
                    group_kind="main_continuity",
                    member_media_ids=("100",),
                ),
            ),
            resolver_version="v1",
        )

        AnimeLocalSeriesProjectionService().persist(
            user=self.user,
            source_profile_key="series_view",
            resolver_version="v1",
            resolution=resolution,
            scope_media_ids={"100"},
        )

        existing.refresh_from_db()
        self.assertEqual(existing.discovered_at, discovered_at)

    def test_never_persists_untracked_media(self):
        Anime.objects.get(user=self.user, item__media_id="101").delete()
        resolution = SimpleNamespace(
            resolver_version="v1",
            groups=[
                AnimeLocalSeriesGroup(
                    root_media_id="100",
                    group_kind="main_continuity",
                    member_media_ids=("100", "101"),
                )
            ],
        )

        AnimeLocalSeriesProjectionService().persist(
            user=self.user,
            source_profile_key="series_view",
            resolver_version="v1",
            resolution=resolution,
            scope_media_ids={"100", "101"},
        )

        self.assertEqual(
            set(
                AnimeLocalSeriesMembership.objects.values_list(
                    "media_id",
                    flat=True,
                )
            ),
            {"100"},
        )
