# ruff: noqa: D102
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Anime,
    AnimeSeriesViewMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_franchise_types import AnimeNode
from app.services.anime_series_view_franchise_projection import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
)
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshService,
)


class AnimeSeriesViewFranchiseRefreshTests(TestCase):
    """Test franchise, singleton, cleanup, and scope persistence."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-refresh")

    def create_anime(self, media_id, title=None):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=title or f"Anime {media_id}",
            image=f"https://example.com/{media_id}.jpg",
        )
        anime = Anime(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        anime.save()
        return anime

    @staticmethod
    def node(media_id, title=None, media_type="tv"):
        return AnimeNode(
            media_id=str(media_id),
            title=title or f"Node {media_id}",
            source=Sources.MAL.value,
            media_type=media_type,
            image=f"https://example.com/root-{media_id}.jpg",
            start_date=None,
        )

    def test_all_tracked_snapshot_entries_share_series_line_root(self):
        root = self.node("1", "Root")
        nodes = {
            media_id: self.node(media_id) for media_id in ("1", "2", "3", "4", "5")
        }
        nodes["1"] = root
        for media_id in nodes:
            self.create_anime(media_id)
        snapshot = SimpleNamespace(
            nodes_by_media_id=nodes,
            series_line=[root, nodes["2"]],
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot

        stats = AnimeSeriesViewFranchiseRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["3"])

        memberships = AnimeSeriesViewMembership.objects.filter(user=self.user)
        self.assertEqual(memberships.count(), 5)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"1"},
        )
        self.assertEqual(
            set(memberships.values_list("display_media_id", flat=True)),
            {"1"},
        )
        self.assertEqual(
            set(memberships.values_list("group_kind", flat=True)),
            {GROUP_KIND_FRANCHISE},
        )
        self.assertEqual(stats.franchise_memberships_created, 5)

    def test_empty_series_line_creates_explicit_singletons(self):
        nodes = {media_id: self.node(media_id) for media_id in ("10", "11")}
        for media_id in nodes:
            self.create_anime(media_id)
        snapshot_service = Mock()
        snapshot_service.build.return_value = SimpleNamespace(
            nodes_by_media_id=nodes,
            series_line=[],
        )

        AnimeSeriesViewFranchiseRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["10"])

        memberships = AnimeSeriesViewMembership.objects.filter(user=self.user)
        self.assertEqual(
            set(memberships.values_list("group_kind", flat=True)),
            {GROUP_KIND_SINGLETON},
        )
        for membership in memberships:
            self.assertEqual(membership.root_media_id, membership.media_id)
            self.assertEqual(membership.display_media_id, membership.media_id)

    def test_cleanup_stays_inside_scope_and_direct_membership_is_removed_on_error(self):
        requested = self.create_anime("20")
        outside = self.create_anime("99")
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=requested.item.media_id,
            root_media_id="20",
            display_media_id="20",
        )
        AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=outside.item.media_id,
            root_media_id="99",
            display_media_id="99",
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = RuntimeError("snapshot failed")

        stats = AnimeSeriesViewFranchiseRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["20"])

        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="20",
            ).exists()
        )
        self.assertTrue(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="99",
            ).exists()
        )
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.memberships_deleted, 1)

    def test_removes_untracked_memberships_only_in_built_scope(self):
        tracked = self.create_anime("30")
        outside = self.create_anime("98")
        for media_id in ("30", "31", "98"):
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id=media_id,
                display_media_id=media_id,
            )
        root = self.node("30")
        snapshot_service = Mock()
        snapshot_service.build.return_value = SimpleNamespace(
            nodes_by_media_id={"30": root, "31": self.node("31")},
            series_line=[root],
        )

        AnimeSeriesViewFranchiseRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=[tracked.item.media_id])

        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="31",
            ).exists()
        )
        self.assertTrue(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id=outside.item.media_id,
            ).exists()
        )

    def test_updates_existing_membership_without_creating_a_duplicate(self):
        first = self.create_anime("40")
        self.create_anime("41")
        membership = AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=first.item.media_id,
            root_media_id="old",
            display_media_id="old",
            group_kind=GROUP_KIND_SINGLETON,
        )
        root = self.node("40", "Updated Root")
        snapshot_service = Mock()
        snapshot_service.build.return_value = SimpleNamespace(
            nodes_by_media_id={"40": root, "41": self.node("41")},
            series_line=[root],
        )

        stats = AnimeSeriesViewFranchiseRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["41"])

        membership.refresh_from_db()
        self.assertEqual(membership.root_media_id, "40")
        self.assertEqual(membership.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="40",
            ).count(),
            1,
        )
        self.assertEqual(stats.franchise_memberships_updated, 1)
