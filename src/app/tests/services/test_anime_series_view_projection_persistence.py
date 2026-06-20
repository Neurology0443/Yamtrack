# ruff: noqa: D101, D102, D103

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import AnimeSeriesViewMembership
from app.services.anime_series_view_projection import (
    AnimeSeriesViewDisplay,
    AnimeSeriesViewGroup,
    AnimeSeriesViewProjection,
)
from app.services.anime_series_view_projection_persistence import (
    AnimeSeriesViewProjectionPersistenceService,
)


def projection(*groups):
    return AnimeSeriesViewProjection(groups=groups, projection_version="v2")


def group(
    root,
    members,
    *,
    display=None,
    kind="main_continuity",
    parent=None,
    parent_title=None,
):
    display_id = display or root
    return AnimeSeriesViewGroup(
        root_media_id=root,
        display_media_id=display_id,
        display=AnimeSeriesViewDisplay(
            media_id=display_id,
            title=f"Display {display_id}",
            image=f"https://example.com/{display_id}.jpg",
            media_type="tv",
            start_date=date(2020, 1, 1),
        ),
        group_kind=kind,
        member_media_ids=tuple(members),
        context_parent_media_id=parent,
        context_parent_title=parent_title,
        context_relation_type="spin_off" if parent else None,
    )


class AnimeSeriesViewProjectionPersistenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="projection")
        self.service = AnimeSeriesViewProjectionPersistenceService()

    def test_create_and_update_memberships(self):
        created = self.service.persist(
            user=self.user,
            projection=projection(group("1", ("1", "2"))),
            scope_media_ids={"1", "2"},
        )
        updated = self.service.persist(
            user=self.user,
            projection=projection(
                group("1", ("1", "2"), display="2", kind="singleton")
            ),
            scope_media_ids={"1", "2"},
        )

        self.assertEqual(created.memberships_created, 2)
        self.assertEqual(updated.memberships_updated, 2)
        membership = AnimeSeriesViewMembership.objects.get(media_id="1")
        self.assertEqual(membership.display_media_id, "2")
        self.assertEqual(membership.display_title, "Display 2")
        self.assertEqual(
            membership.display_image,
            "https://example.com/2.jpg",
        )
        self.assertEqual(membership.display_media_type, "tv")
        self.assertEqual(membership.display_start_date, date(2020, 1, 1))
        self.assertEqual(membership.group_kind, "singleton")

    def test_persists_context_parent_title(self):
        self.service.persist(
            user=self.user,
            projection=projection(
                group(
                    "2",
                    ("2",),
                    parent="1",
                    parent_title="Main Anime",
                )
            ),
            scope_media_ids={"1", "2"},
        )

        membership = AnimeSeriesViewMembership.objects.get(media_id="2")
        self.assertEqual(membership.context_parent_title, "Main Anime")

    def test_non_member_root_display_and_parent_do_not_fail_scope_validation(self):
        stats = self.service.persist(
            user=self.user,
            projection=projection(
                group(
                    "root",
                    ("tracked",),
                    display="display",
                    parent="parent",
                    parent_title="Parent",
                )
            ),
            scope_media_ids={"tracked"},
        )

        self.assertEqual(stats.memberships_created, 1)

    def test_delete_stale_only_inside_scope(self):
        for media_id in ("1", "2", "outside"):
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id=media_id,
                display_media_id=media_id,
                group_kind="singleton",
                component_size=1,
                projection_version="v2",
                source_profile_key="series_view",
            )

        stats = self.service.persist(
            user=self.user,
            projection=projection(group("1", ("1",), kind="singleton")),
            scope_media_ids={"1", "2"},
        )

        self.assertEqual(stats.memberships_deleted, 1)
        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(media_id="2").exists()
        )
        self.assertTrue(
            AnimeSeriesViewMembership.objects.filter(media_id="outside").exists()
        )

    def test_rejects_projection_outside_scope(self):
        with self.assertRaisesMessage(
            ValueError,
            "projection contains media outside snapshot scope",
        ):
            self.service.persist(
                user=self.user,
                projection=projection(group("1", ("1", "2"))),
                scope_media_ids={"1"},
            )

    def test_dry_run_does_not_write(self):
        stats = self.service.persist(
            user=self.user,
            projection=projection(group("1", ("1",))),
            scope_media_ids={"1"},
            dry_run=True,
        )

        self.assertEqual(stats.memberships_recorded, 1)
        self.assertFalse(AnimeSeriesViewMembership.objects.exists())
