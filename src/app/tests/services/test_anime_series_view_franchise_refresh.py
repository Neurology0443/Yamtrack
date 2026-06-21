# ruff: noqa: D102
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.anime_series_view_constants import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
)
from app.providers import services
from app.models import (
    Anime,
    AnimeSeriesViewMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshService,
)
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjection,
    AnimeSeriesViewProjectionRoot,
)


class AnimeSeriesViewFranchiseRefreshTests(TestCase):
    """Test non-destructive refresh, delete cleanup, and scoped persistence."""

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
    def projection(
        *,
        seed,
        root,
        members,
        group_kind=GROUP_KIND_FRANCHISE,
    ):
        return AnimeSeriesViewProjection(
            seed_media_id=str(seed),
            root=AnimeSeriesViewProjectionRoot(
                media_id=str(root),
                title=f"Root {root}",
                image=f"https://example.com/root-{root}.jpg",
                media_type="tv",
                start_date=None,
            ),
            member_media_ids=tuple(str(member) for member in members),
            group_kind=group_kind,
            projection_version=PROJECTION_VERSION,
        )

    def service(self, projection):
        builder = Mock()
        builder.build.return_value = projection
        return AnimeSeriesViewFranchiseRefreshService(
            projection_builder=builder
        ), builder

    @staticmethod
    def unresolved_projection(seed, members):
        return AnimeSeriesViewProjection(
            seed_media_id=str(seed),
            root=None,
            member_media_ids=tuple(str(member) for member in members),
            group_kind=None,
            projection_version=PROJECTION_VERSION,
            is_confident=False,
            skip_reason="weak_reroot_unconfirmed",
        )

    def test_normal_refresh_preserves_old_membership_on_projection_error(self):
        anime = self.create_anime("20")
        membership = AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=anime.item.media_id,
            root_media_id="old-root",
            display_media_id="old-root",
        )
        builder = Mock()
        builder.build.side_effect = RuntimeError("snapshot unavailable")

        stats = AnimeSeriesViewFranchiseRefreshService(
            projection_builder=builder
        ).refresh_for_media_ids(user=self.user, media_ids=["20"])

        membership.refresh_from_db()
        self.assertEqual(membership.root_media_id, "old-root")
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.snapshots_skipped, 1)
        self.assertEqual(stats.memberships_deleted, 0)

    def test_retryable_provider_error_is_recorded_without_deleting_membership(self):
        anime = self.create_anime("20")
        membership = AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=anime.item.media_id,
            root_media_id="old-root",
            display_media_id="old-root",
        )
        response = Mock(status_code=504, text="Gateway Timeout")
        error = requests.exceptions.HTTPError(response=response)
        builder = Mock()
        builder.build.side_effect = services.ProviderAPIError(Sources.MAL.value, error)

        stats = AnimeSeriesViewFranchiseRefreshService(
            projection_builder=builder
        ).refresh_for_media_ids(user=self.user, media_ids=["20"])

        membership.refresh_from_db()
        self.assertEqual(membership.root_media_id, "old-root")
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.retryable_errors, 1)
        self.assertEqual(stats.retryable_media_ids, ["20"])

    def test_delete_removes_only_direct_membership_when_projection_fails(self):
        for media_id in ("30", "31", "32"):
            self.create_anime(media_id)
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id="30",
                display_media_id="30",
            )
        builder = Mock()
        builder.build.side_effect = RuntimeError("snapshot unavailable")

        stats = AnimeSeriesViewFranchiseRefreshService(
            projection_builder=builder
        ).refresh_after_delete(user=self.user, media_ids=["31"])

        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="31",
            ).exists()
        )
        self.assertEqual(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id__in=["30", "32"],
            ).count(),
            2,
        )
        self.assertEqual(stats.memberships_deleted, 1)
        self.assertEqual(stats.errors, 1)

    def test_unresolved_projection_preserves_existing_membership(self):
        anime = self.create_anime("35")
        membership = AnimeSeriesViewMembership.objects.create(
            user=self.user,
            media_id=anime.item.media_id,
            root_media_id="old-root",
            display_media_id="old-root",
        )
        service, _builder = self.service(self.unresolved_projection("35", ("35", "36")))

        stats = service.refresh_for_media_ids(
            user=self.user,
            media_ids=["35"],
        )

        membership.refresh_from_db()
        self.assertEqual(membership.root_media_id, "old-root")
        self.assertEqual(stats.snapshots_skipped, 1)
        self.assertEqual(stats.memberships_deleted, 0)

    def test_delete_with_unresolved_projection_preserves_other_memberships(self):
        for media_id in ("36", "37", "38"):
            self.create_anime(media_id)
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id="36",
                display_media_id="36",
            )
        service, _builder = self.service(
            self.unresolved_projection("37", ("36", "37", "38"))
        )

        stats = service.refresh_after_delete(
            user=self.user,
            media_ids=["37"],
        )

        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="37",
            ).exists()
        )
        self.assertEqual(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id__in=["36", "38"],
            ).count(),
            2,
        )
        self.assertEqual(stats.snapshots_skipped, 1)
        self.assertEqual(stats.memberships_deleted, 1)

    def test_franchise_projection_persists_all_tracked_members_under_one_root(self):
        self.create_anime("42916")
        self.create_anime("50275")
        service, _builder = self.service(
            self.projection(
                seed="42916",
                root="11757",
                members=("11757", "42916", "50275"),
            )
        )

        stats = service.refresh_for_media_ids(
            user=self.user,
            media_ids=["42916"],
        )

        memberships = AnimeSeriesViewMembership.objects.filter(user=self.user)
        self.assertEqual(memberships.count(), 2)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"11757"},
        )
        self.assertEqual(
            set(memberships.values_list("group_kind", flat=True)),
            {GROUP_KIND_FRANCHISE},
        )
        self.assertEqual(stats.franchise_memberships_created, 2)

    def test_singleton_projection_persists_only_explicit_singleton(self):
        self.create_anime("900")
        self.create_anime("901")
        service, _builder = self.service(
            self.projection(
                seed="900",
                root="900",
                members=("900",),
                group_kind=GROUP_KIND_SINGLETON,
            )
        )

        service.refresh_for_media_ids(user=self.user, media_ids=["900"])

        membership = AnimeSeriesViewMembership.objects.get(
            user=self.user,
            media_id="900",
        )
        self.assertEqual(membership.root_media_id, "900")
        self.assertEqual(membership.group_kind, GROUP_KIND_SINGLETON)
        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="901",
            ).exists()
        )

    def test_stale_cleanup_is_limited_to_projection_members(self):
        tracked = self.create_anime("40")
        outside = self.create_anime("99")
        for media_id in ("40", "41", "99"):
            AnimeSeriesViewMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id=media_id,
                display_media_id=media_id,
            )
        service, _builder = self.service(
            self.projection(
                seed=tracked.item.media_id,
                root="40",
                members=("40", "41"),
            )
        )

        service.refresh_for_media_ids(
            user=self.user,
            media_ids=[tracked.item.media_id],
        )

        self.assertFalse(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id="41",
            ).exists()
        )
        self.assertTrue(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id=outside.item.media_id,
            ).exists()
        )

    def test_refresh_skips_build_for_ids_covered_by_successful_projection(self):
        self.create_anime("50")
        self.create_anime("51")
        projection = self.projection(
            seed="50",
            root="50",
            members=("50", "51"),
        )
        builder = Mock()
        builder.build.return_value = projection
        service = AnimeSeriesViewFranchiseRefreshService(projection_builder=builder)

        stats = service.refresh_for_media_ids(
            user=self.user,
            media_ids=["50", "51"],
        )

        builder.build.assert_called_once_with("50", refresh_cache=False)
        self.assertEqual(stats.snapshots_skipped, 1)
        self.assertEqual(stats.franchise_memberships_created, 2)

    def test_refresh_does_not_cover_projection_when_persistence_fails(self):
        self.create_anime("70")
        self.create_anime("71")
        projection = self.projection(
            seed="70",
            root="70",
            members=("70", "71"),
        )
        builder = Mock()
        builder.build.return_value = projection
        service = AnimeSeriesViewFranchiseRefreshService(projection_builder=builder)
        original_persist = service._persist_projection
        persist_calls = 0

        def persist_with_first_failure(**kwargs):
            nonlocal persist_calls
            persist_calls += 1
            if persist_calls == 1:
                message = "database unavailable"
                raise RuntimeError(message)
            return original_persist(**kwargs)

        with patch.object(
            service,
            "_persist_projection",
            side_effect=persist_with_first_failure,
        ):
            stats = service.refresh_for_media_ids(
                user=self.user,
                media_ids=["70", "71"],
            )

        self.assertEqual(builder.build.call_count, 2)
        self.assertEqual(stats.errors, 1)
        self.assertEqual(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id__in=["70", "71"],
            ).count(),
            2,
        )

    def test_independent_remake_and_old_continuity_persist_separately(self):
        for media_id in ("2966", "51122", "59928"):
            self.create_anime(media_id)
        old_projection = self.projection(
            seed="2966",
            root="2966",
            members=("2966",),
        )
        remake_projection = self.projection(
            seed="51122",
            root="51122",
            members=("51122", "59928"),
        )
        builder = Mock()
        builder.build.side_effect = lambda media_id, **_kwargs: (
            old_projection if media_id == "2966" else remake_projection
        )

        stats = AnimeSeriesViewFranchiseRefreshService(
            projection_builder=builder
        ).refresh_for_media_ids(
            user=self.user,
            media_ids=["51122", "59928", "2966"],
        )

        memberships = {
            membership.media_id: membership
            for membership in AnimeSeriesViewMembership.objects.filter(user=self.user)
        }
        self.assertEqual(memberships["2966"].root_media_id, "2966")
        self.assertEqual(memberships["2966"].display_media_id, "2966")
        self.assertEqual(memberships["51122"].root_media_id, "51122")
        self.assertEqual(memberships["51122"].display_media_id, "51122")
        self.assertEqual(memberships["59928"].root_media_id, "51122")
        self.assertEqual(memberships["59928"].display_media_id, "51122")
        self.assertEqual(stats.snapshots_built, 2)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_branch_continuation_member_is_persisted_under_main_root(self):
        self.create_anime("82")
        service, _builder = self.service(
            self.projection(
                seed="82",
                root="80",
                members=("80", "81", "82"),
            )
        )

        service.refresh_for_media_ids(user=self.user, media_ids=["82"])

        membership = AnimeSeriesViewMembership.objects.get(
            user=self.user,
            media_id="82",
        )
        self.assertEqual(membership.root_media_id, "80")
