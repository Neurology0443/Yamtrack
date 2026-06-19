# ruff: noqa: D101, D102

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    Anime,
    AnimeImportComponentMembership,
    AnimeImportScanState,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_component_membership import (
    AnimeImportComponentMembershipService,
    LocalComponentMembership,
)
from app.services.anime_franchise_types import AnimeRelation


class AnimeImportComponentMembershipServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="component-map")
        self.service = AnimeImportComponentMembershipService()

    def create_anime(self, media_id):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=f"Anime {media_id}",
            image=f"https://example.com/{media_id}.jpg",
        )
        anime = Anime(
            user=self.user,
            item=item,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        anime.save()

    def test_resolver_keeps_alternative_branch_separate_from_global_parent(self):
        snapshot = type(
            "Snapshot",
            (),
            {
                "all_normalized_relations": [
                    AnimeRelation("223", "502", "alternative_version"),
                    AnimeRelation("223", "891", "alternative_version"),
                    AnimeRelation("223", "892", "alternative_version"),
                    AnimeRelation("223", "893", "alternative_version"),
                    AnimeRelation("502", "891", "sequel"),
                    AnimeRelation("891", "892", "sequel"),
                    AnimeRelation("892", "893", "sequel"),
                ],
            },
        )()

        memberships = self.service.resolve_local_memberships(
            snapshot=snapshot,
            selected_media_ids={"223", "502", "891", "892", "893"},
        )

        self.assertEqual(
            {
                membership.media_id: membership.component_root_mal_id
                for membership in memberships
            },
            {
                "223": "223",
                "502": "502",
                "891": "502",
                "892": "502",
                "893": "502",
            },
        )

    def test_resolver_does_not_collapse_other_branch_relations(self):
        snapshot = type(
            "Snapshot",
            (),
            {
                "all_normalized_relations": [
                    AnimeRelation("100", "200", "alternative_setting"),
                    AnimeRelation("100", "300", "spin_off"),
                ],
            },
        )()

        memberships = self.service.resolve_local_memberships(
            snapshot=snapshot,
            selected_media_ids={"100", "200", "300"},
        )

        self.assertEqual(
            {
                membership.media_id: membership.component_root_mal_id
                for membership in memberships
            },
            {
                "100": "100",
                "200": "200",
                "300": "300",
            },
        )

    def test_resolver_expands_selected_branch_through_local_relations(self):
        snapshot = type(
            "Snapshot",
            (),
            {
                "all_normalized_relations": [
                    AnimeRelation("223", "502", "alternative_version"),
                    AnimeRelation("502", "891", "sequel"),
                    AnimeRelation("891", "892", "sequel"),
                    AnimeRelation("892", "893", "sequel"),
                ],
            },
        )()

        memberships = self.service.resolve_local_memberships(
            snapshot=snapshot,
            selected_media_ids={"502"},
        )

        self.assertEqual(
            {
                membership.media_id: membership.component_root_mal_id
                for membership in memberships
            },
            {
                "502": "502",
                "891": "502",
                "892": "502",
                "893": "502",
            },
        )

    def test_record_tracked_memberships_upserts_without_untracked_rows(self):
        self.create_anime("100")
        self.create_anime("101")

        recorded = self.service.record_tracked_memberships(
            user_id=self.user.id,
            memberships=[
                LocalComponentMembership("100", "100", 3),
                LocalComponentMembership("101", "100", 3),
                LocalComponentMembership("102", "100", 3),
            ],
            source_profile_key="continuity",
        )
        updated = self.service.record_tracked_memberships(
            user_id=self.user.id,
            memberships=[
                LocalComponentMembership("100", "99", 4),
                LocalComponentMembership("101", "99", 4),
                LocalComponentMembership("102", "99", 4),
            ],
            source_profile_key="complete",
        )
        expected_component_size = 4

        self.assertEqual(recorded, 2)
        self.assertEqual(updated, 2)
        memberships = list(
            AnimeImportComponentMembership.objects.filter(
                user=self.user,
            ).order_by("media_id"),
        )
        self.assertEqual(
            [membership.media_id for membership in memberships],
            ["100", "101"],
        )
        self.assertTrue(
            all(
                membership.component_root_mal_id == "99"
                and membership.component_size == expected_component_size
                and membership.source_profile_key == "complete"
                for membership in memberships
            ),
        )

    def test_membership_write_does_not_modify_scan_scheduler_state(self):
        self.create_anime("100")
        state = AnimeImportScanState.objects.create(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
            next_scan_at=timezone.now(),
            last_success_at=timezone.now(),
            last_result_fingerprint="fingerprint",
        )
        original_scheduler_values = (
            state.next_scan_at,
            state.last_success_at,
            state.last_result_fingerprint,
        )

        self.service.record_tracked_memberships(
            user_id=self.user.id,
            memberships=[LocalComponentMembership("100", "99", 1)],
            source_profile_key="complete",
        )

        state.refresh_from_db()
        self.assertEqual(
            (
                state.next_scan_at,
                state.last_success_at,
                state.last_result_fingerprint,
            ),
            original_scheduler_values,
        )
