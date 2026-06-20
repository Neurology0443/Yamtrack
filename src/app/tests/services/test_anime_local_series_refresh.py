# ruff: noqa: D101,D102,D103
from unittest.mock import Mock, patch

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
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_local_series_refresh import (
    AnimeLocalSeriesProjectionRefreshService,
)


def make_node(media_id, *, media_type="tv"):
    return AnimeNode(
        str(media_id),
        f"Anime {media_id}",
        "mal",
        media_type,
        "image",
        None,
    )


def make_snapshot(root_id, nodes, relations, *, canonical_root_id=None):
    nodes_by_id = {item.media_id: item for item in nodes}
    for relation in relations:
        nodes_by_id[relation.source_media_id].relations.append(relation)
    return AnimeFranchiseSnapshot(
        root_node=nodes_by_id[root_id],
        nodes_by_media_id=nodes_by_id,
        all_normalized_relations=relations,
        continuity_component=list(nodes),
        series_line=list(nodes),
        direct_anchors=[nodes_by_id[root_id]],
        direct_candidates=[],
        has_series_line=True,
        fallback_anchor_media_id=root_id,
        canonical_root_media_id=canonical_root_id or root_id,
    )


class AnimeLocalSeriesProjectionRefreshTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="series-user")

    def track(self, media_id):
        item = Item.objects.create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title=f"Anime {media_id}",
            image="image",
        )
        anime = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        anime._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            anime.save()

    def test_satellite_refresh_rebuilds_canonical_rezero(self):
        media_ids = ["31240", "36286", "38414", "39587", "42203", "54857", "61316"]
        for media_id in media_ids:
            self.track(media_id)
        local_nodes = [make_node("36286", media_type="movie"), make_node("31240")]
        local_relations = [
            AnimeRelation("36286", "31240", "parent_story"),
            AnimeRelation("31240", "36286", "side_story"),
        ]
        canonical_nodes = [make_node(media_id) for media_id in media_ids]
        canonical_relations = [
            AnimeRelation("31240", "38414", "prequel"),
            AnimeRelation("38414", "31240", "sequel"),
            AnimeRelation("31240", "39587", "sequel"),
            AnimeRelation("39587", "42203", "sequel"),
            AnimeRelation("42203", "54857", "sequel"),
            AnimeRelation("54857", "61316", "sequel"),
            AnimeRelation("31240", "36286", "side_story"),
            AnimeRelation("36286", "31240", "parent_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            make_snapshot("36286", local_nodes, local_relations),
            make_snapshot(
                "31240",
                canonical_nodes,
                canonical_relations,
                canonical_root_id="38414",
            ),
        ]

        stats = AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["36286"])

        memberships = AnimeLocalSeriesMembership.objects.filter(user=self.user)
        self.assertEqual(memberships.count(), 7)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"38414"},
        )
        self.assertEqual(stats.memberships_created, 7)

    def test_satellite_without_tracked_parent_persists_only_satellite(self):
        self.track("33372")
        nodes = [make_node("29803"), make_node("33372", media_type="special")]
        relations = [
            AnimeRelation("33372", "29803", "parent_story"),
            AnimeRelation("29803", "33372", "side_story"),
        ]
        local = make_snapshot("33372", nodes, relations)
        canonical = make_snapshot(
            "29803",
            nodes,
            relations,
            canonical_root_id="29803",
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [local, canonical]

        AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["33372"])

        membership = AnimeLocalSeriesMembership.objects.get(user=self.user)
        self.assertEqual(membership.media_id, "33372")
        self.assertEqual(membership.context_parent_media_id, "29803")
        self.assertFalse(
            AnimeLocalSeriesMembership.objects.filter(media_id="29803").exists()
        )

    def test_failed_canonical_rebuild_preserves_existing_projection(self):
        self.track("36286")
        AnimeLocalSeriesMembership.objects.create(
            user=self.user,
            media_id="36286",
            root_media_id="old-root",
            group_kind="singleton",
            source_profile_key="series_view",
            resolver_version="v1",
        )
        local_nodes = [make_node("36286"), make_node("31240")]
        local_relations = [AnimeRelation("36286", "31240", "parent_story")]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            make_snapshot("36286", local_nodes, local_relations),
            RuntimeError("canonical unavailable"),
        ]

        stats = AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["36286"])

        membership = AnimeLocalSeriesMembership.objects.get(user=self.user)
        self.assertEqual(membership.root_media_id, "old-root")
        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.canonical_roots_skipped, 1)

    def test_dry_run_does_not_write(self):
        self.track("100")
        canonical = make_snapshot("100", [make_node("100")], [])
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [canonical, canonical]

        stats = AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(
            user=self.user,
            media_ids=["100"],
            dry_run=True,
        )

        self.assertEqual(stats.memberships_recorded, 1)
        self.assertEqual(stats.dry_run_skips, 1)
        self.assertFalse(AnimeLocalSeriesMembership.objects.exists())

    def test_parent_added_after_satellite_rebuilds_shared_group(self):
        self.track("33372")
        nodes = [make_node("29803"), make_node("33372", media_type="special")]
        relations = [
            AnimeRelation("33372", "29803", "parent_story"),
            AnimeRelation("29803", "33372", "side_story"),
        ]
        local = make_snapshot("33372", nodes, relations)
        canonical = make_snapshot("29803", nodes, relations)
        first_snapshot_service = Mock()
        first_snapshot_service.build.side_effect = [local, canonical]
        AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=first_snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["33372"])

        self.track("29803")
        second_snapshot_service = Mock()
        second_snapshot_service.build.return_value = canonical
        AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=second_snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["29803"])

        memberships = AnimeLocalSeriesMembership.objects.filter(user=self.user)
        self.assertEqual(memberships.count(), 2)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"29803"},
        )

    def test_deleted_media_membership_is_removed_from_canonical_scope(self):
        self.track("100")
        self.track("101")
        nodes = [make_node("100"), make_node("101")]
        relations = [AnimeRelation("100", "101", "sequel")]
        canonical = make_snapshot("100", nodes, relations)
        service = AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=Mock(build=Mock(return_value=canonical))
        )
        service.refresh_for_media_ids(user=self.user, media_ids=["100"])

        Anime.objects.get(user=self.user, item__media_id="101").delete()
        service.refresh_for_media_ids(user=self.user, media_ids=["101"])

        self.assertEqual(
            set(
                AnimeLocalSeriesMembership.objects.filter(
                    user=self.user
                ).values_list("media_id", flat=True)
            ),
            {"100"},
        )

    def test_multiple_affected_ids_persist_same_franchise_once(self):
        for media_id in ("100", "101"):
            self.track(media_id)
        nodes = [make_node("100"), make_node("101")]
        relations = [AnimeRelation("100", "101", "sequel")]
        canonical = make_snapshot(
            "100",
            nodes,
            relations,
            canonical_root_id="100",
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = canonical
        projection_service = Mock()
        projection_service.persist.return_value = Mock(
            memberships_recorded=2,
            memberships_created=2,
            memberships_updated=0,
            memberships_deleted=0,
        )

        stats = AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service,
            projection_service=projection_service,
        ).refresh_for_media_ids(
            user=self.user,
            media_ids=["100", "101", "100"],
        )

        projection_service.persist.assert_called_once()
        self.assertEqual(stats.canonical_roots_considered, 1)

    def test_fragmented_existing_projection_is_repaired(self):
        media_ids = ["31240", "36286", "38414", "39587", "42203", "54857", "61316"]
        for media_id in media_ids:
            self.track(media_id)
        for media_id, root_media_id in (
            ("36286", "36286"),
            ("42203", "38414"),
            ("54857", "38414"),
            ("61316", "38414"),
        ):
            AnimeLocalSeriesMembership.objects.create(
                user=self.user,
                media_id=media_id,
                root_media_id=root_media_id,
                group_kind="singleton",
                source_profile_key="series_view",
                resolver_version="v1",
            )

        local_nodes = [make_node("36286", media_type="movie"), make_node("31240")]
        local_relations = [
            AnimeRelation("36286", "31240", "parent_story"),
            AnimeRelation("31240", "36286", "side_story"),
        ]
        canonical_nodes = [make_node(media_id) for media_id in media_ids]
        canonical_relations = [
            AnimeRelation("31240", "38414", "prequel"),
            AnimeRelation("38414", "31240", "sequel"),
            AnimeRelation("31240", "39587", "sequel"),
            AnimeRelation("39587", "42203", "sequel"),
            AnimeRelation("42203", "54857", "sequel"),
            AnimeRelation("54857", "61316", "sequel"),
            AnimeRelation("31240", "36286", "side_story"),
            AnimeRelation("36286", "31240", "parent_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            make_snapshot("36286", local_nodes, local_relations),
            make_snapshot(
                "31240",
                canonical_nodes,
                canonical_relations,
                canonical_root_id="38414",
            ),
        ]

        AnimeLocalSeriesProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(user=self.user, media_ids=["36286"])

        memberships = AnimeLocalSeriesMembership.objects.filter(user=self.user)
        self.assertEqual(memberships.count(), 7)
        self.assertEqual(
            set(memberships.values_list("root_media_id", flat=True)),
            {"38414"},
        )
