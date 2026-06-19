# ruff: noqa: D101, D102

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Anime,
    AnimeImportComponentMembership,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_component_membership import (
    AnimeImportComponentMembershipService,
)


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

    def test_record_tracked_component_upserts_without_untracked_rows(self):
        self.create_anime("100")
        self.create_anime("101")

        recorded = self.service.record_tracked_component(
            user_id=self.user.id,
            media_ids={"100", "101", "102"},
            component_root_mal_id="100",
            component_size=3,
            source_profile_key="continuity",
        )
        updated = self.service.record_tracked_component(
            user_id=self.user.id,
            media_ids={"100", "101", "102"},
            component_root_mal_id="99",
            component_size=4,
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
