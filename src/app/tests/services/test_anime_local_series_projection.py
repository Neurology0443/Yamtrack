# ruff: noqa: D101,D102,S106
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

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
    LocalSeriesGroup,
    LocalSeriesResolution,
)


class AnimeLocalSeriesProjectionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="series-projection",
            password="pwd",
        )
        self.service = AnimeLocalSeriesProjectionService()

    def _track(self, *media_ids):
        items = [
            Item.objects.create(
                media_id=str(media_id),
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=f"Anime {media_id}",
                image=f"https://example.com/{media_id}.jpg",
            )
            for media_id in media_ids
        ]
        Anime.objects.bulk_create(
            [
                Anime(
                    user=self.user,
                    item=item,
                    status=Status.PLANNING.value,
                )
                for item in items
            ]
        )

    @staticmethod
    def _resolution(*groups, version="v1"):
        return LocalSeriesResolution(
            groups=list(groups),
            resolver_version=version,
        )

    @staticmethod
    def _group(
        root_media_id,
        member_media_ids,
        *,
        group_kind="main_continuity",
        context_parent_media_id=None,
        context_relation_type=None,
    ):
        return LocalSeriesGroup(
            root_media_id=str(root_media_id),
            group_kind=group_kind,
            member_media_ids=[str(media_id) for media_id in member_media_ids],
            context_parent_media_id=context_parent_media_id,
            context_relation_type=context_relation_type,
        )

    def test_persists_complete_membership_projection(self):
        self._track("10", "20")
        resolution = self._resolution(
            self._group(
                "10",
                ["10", "20"],
                group_kind="alternative_branch",
                context_parent_media_id="1",
                context_relation_type="alternative_version",
            )
        )

        stats = self.service.persist(
            user=self.user,
            resolution=resolution,
            source_profile_key="complete",
            scope_media_ids={"10", "20"},
        )

        memberships = list(
            AnimeLocalSeriesMembership.objects.order_by("media_id")
        )
        self.assertEqual(stats.memberships_recorded, 2)
        self.assertEqual(stats.memberships_created, 2)
        self.assertEqual(stats.memberships_updated, 0)
        self.assertEqual(len(memberships), 2)
        self.assertEqual(
            {
                (
                    membership.media_id,
                    membership.root_media_id,
                    membership.group_kind,
                    membership.context_parent_media_id,
                    membership.context_relation_type,
                    membership.component_size,
                    membership.source_profile_key,
                    membership.resolver_version,
                )
                for membership in memberships
            },
            {
                (
                    "10",
                    "10",
                    "alternative_branch",
                    "1",
                    "alternative_version",
                    2,
                    "complete",
                    "v1",
                ),
                (
                    "20",
                    "10",
                    "alternative_branch",
                    "1",
                    "alternative_version",
                    2,
                    "complete",
                    "v1",
                ),
            },
        )

    def test_filters_members_that_are_not_actually_tracked(self):
        self._track("10")
        resolution = self._resolution(self._group("10", ["10", "20"]))

        stats = self.service.persist(
            user=self.user,
            resolution=resolution,
            source_profile_key="continuity",
            scope_media_ids={"10", "20"},
        )

        membership = AnimeLocalSeriesMembership.objects.get()
        self.assertEqual(stats.memberships_recorded, 1)
        self.assertEqual(membership.media_id, "10")
        self.assertEqual(membership.component_size, 1)

    def test_updates_membership_without_resetting_discovered_at(self):
        self._track("10")
        membership = AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="10",
            root_media_id="10",
            group_kind="singleton",
            component_size=1,
            source_profile_key="complete",
            resolver_version="v1",
        )
        old_discovered_at = timezone.now() - timedelta(days=3)
        AnimeLocalSeriesMembership.objects.filter(pk=membership.pk).update(
            discovered_at=old_discovered_at,
            updated_at=old_discovered_at,
        )
        resolution = self._resolution(
            self._group(
                "10",
                ["10"],
                group_kind="spin_off_branch",
                context_parent_media_id="1",
                context_relation_type="spin_off",
            )
        )

        stats = self.service.persist(
            user=self.user,
            resolution=resolution,
            source_profile_key="complete",
            scope_media_ids={"10"},
        )

        membership.refresh_from_db()
        self.assertEqual(stats.memberships_created, 0)
        self.assertEqual(stats.memberships_updated, 1)
        self.assertEqual(membership.discovered_at, old_discovered_at)
        self.assertGreater(membership.updated_at, old_discovered_at)
        self.assertEqual(membership.group_kind, "spin_off_branch")
        self.assertEqual(membership.context_parent_media_id, "1")

    def test_deletes_stale_memberships_in_same_projection_scope(self):
        self._track("10", "20")
        self.service.persist(
            user=self.user,
            resolution=self._resolution(self._group("10", ["10", "20"])),
            source_profile_key="complete",
            scope_media_ids={"10", "20"},
        )

        stats = self.service.persist(
            user=self.user,
            resolution=self._resolution(self._group("10", ["10"])),
            source_profile_key="complete",
            scope_media_ids={"10", "20"},
        )

        self.assertEqual(stats.memberships_deleted, 1)
        self.assertEqual(
            set(
                AnimeLocalSeriesMembership.objects.values_list(
                    "media_id",
                    flat=True,
                )
            ),
            {"10"},
        )

    def test_deletes_older_resolver_versions_for_same_profile(self):
        self._track("10")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="10",
            root_media_id="10",
            group_kind="singleton",
            component_size=1,
            source_profile_key="complete",
            resolver_version="v0",
        )

        stats = self.service.persist(
            user=self.user,
            resolution=self._resolution(
                self._group("10", ["10"]),
                version="v1",
            ),
            source_profile_key="complete",
            scope_media_ids={"10"},
        )

        self.assertEqual(stats.memberships_deleted, 1)
        membership = AnimeLocalSeriesMembership.objects.get()
        self.assertEqual(membership.resolver_version, "v1")

    def test_preserves_other_profile_projections(self):
        self._track("10")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="10",
            root_media_id="10",
            group_kind="singleton",
            component_size=1,
            source_profile_key="continuity",
            resolver_version="v1",
        )

        self.service.persist(
            user=self.user,
            resolution=self._resolution(self._group("10", ["10"])),
            source_profile_key="complete",
            scope_media_ids={"10"},
        )

        self.assertEqual(
            set(
                AnimeLocalSeriesMembership.objects.values_list(
                    "source_profile_key",
                    flat=True,
                )
            ),
            {"continuity", "complete"},
        )

    def test_requires_projection_scope_and_version(self):
        self._track("10")

        with self.assertRaisesRegex(ValueError, "source_profile_key"):
            self.service.persist(
                user=self.user,
                resolution=self._resolution(self._group("10", ["10"])),
                source_profile_key=" ",
                scope_media_ids={"10"},
            )

        with self.assertRaisesRegex(ValueError, "resolver_version"):
            self.service.persist(
                user=self.user,
                resolution=self._resolution(
                    self._group("10", ["10"]),
                    version="",
                ),
                source_profile_key="complete",
                scope_media_ids={"10"},
            )

    def test_projection_scope_preserves_other_franchises(self):
        self._track("10", "20")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="20",
            root_media_id="20",
            group_kind="singleton",
            component_size=1,
            source_profile_key="complete",
            resolver_version="v1",
        )

        self.service.persist(
            user=self.user,
            resolution=self._resolution(self._group("10", ["10"])),
            source_profile_key="complete",
            scope_media_ids={"10"},
        )

        self.assertEqual(
            set(
                AnimeLocalSeriesMembership.objects.values_list(
                    "media_id",
                    flat=True,
                )
            ),
            {"10", "20"},
        )

    def test_replaces_stale_singleton_with_current_continuity_group(self):
        media_ids = {"31240", "38414", "39587", "42203", "54857", "61316"}
        self._track(*sorted(media_ids))
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="31240",
            root_media_id="31240",
            group_kind="singleton",
            component_size=1,
            source_profile_key="series_view",
            resolver_version="v1",
        )
        resolution = self._resolution(
            self._group(
                "38414",
                ["38414", "31240", "39587", "42203", "54857", "61316"],
            )
        )

        stats = self.service.persist(
            user=self.user,
            resolution=resolution,
            source_profile_key="series_view",
            scope_media_ids=media_ids,
        )

        self.assertEqual(stats.memberships_recorded, 6)
        memberships = AnimeLocalSeriesMembership.objects.filter(
            user=self.user,
            source_profile_key="series_view",
        )
        self.assertEqual(memberships.count(), 6)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"38414"},
        )
        stale_membership = memberships.get(media_id="31240")
        self.assertEqual(stale_membership.group_kind, "main_continuity")
        self.assertEqual(stale_membership.component_size, 6)

    def test_rejects_resolution_outside_projection_scope(self):
        self._track("10")

        with self.assertRaisesRegex(ValueError, "outside projection scope"):
            self.service.persist(
                user=self.user,
                resolution=self._resolution(self._group("10", ["10"])),
                source_profile_key="complete",
                scope_media_ids={"20"},
            )
