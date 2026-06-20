# ruff: noqa: D101, D102

from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryStats
from app.services.anime_franchise_import import AnimeFranchiseImportService
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_series_view_projection_refresh import (
    AnimeSeriesViewProjectionRefreshService,
)


class AnimeSeriesViewImportIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="batch-import")
        item = Item.objects.create(
            media_id="321",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Seed",
            image="https://example.com/seed.jpg",
        )
        seed = Anime(user=self.user, item=item, status=Status.PLANNING.value)
        seed._skip_hot_priority = True
        with patch.object(Item, "fetch_releases"):
            seed.save()

    @patch(
        "app.signals.AnimeSeriesViewRefreshTriggerService.schedule_import_batch"
    )
    @patch("app.services.anime_franchise_import.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.get_import_profile")
    def test_multi_entry_import_triggers_one_coherent_series_refresh(
        self,
        get_profile,
        anime_minimal,
        schedule_import_batch,
    ):
        snapshot = SimpleNamespace(
            continuity_component=[object(), object(), object()],
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        profile = Mock()
        profile.is_seed_eligible.return_value = True
        profile.component_root_media_id.return_value = "321"
        profile.select.return_value = SimpleNamespace(
            media_ids={"123", "124"},
            fingerprint_payload={"selected": ["123", "124"]},
        )
        profile.detail_cache_warm_media_ids.return_value = set()
        get_profile.return_value = profile
        anime_minimal.side_effect = [
            {
                "title": "Imported 123",
                "image": "https://example.com/123.jpg",
            },
            {
                "title": "Imported 124",
                "image": "https://example.com/124.jpg",
            },
        ]
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = (
            AnimeFranchiseDiscoveryStats()
        )
        service = AnimeFranchiseImportService(
            snapshot_service=snapshot_service,
            cache_warm_scheduler=Mock(),
            discovery_service=discovery_service,
        )

        with patch.object(Item, "fetch_releases"):
            stats = service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=True,
                limit=1,
                refresh_cache=False,
                user_ids=[self.user.id],
            )

        self.assertEqual(stats.created, 2)
        schedule_import_batch.assert_called_once_with(
            user=self.user,
            seed_media_id="321",
            component_root_media_id="321",
        )

        nodes = [
            AnimeNode(
                media_id=media_id,
                title=f"Anime {media_id}",
                source="mal",
                media_type="tv",
                image=f"https://example.com/{media_id}.jpg",
                start_date=None,
            )
            for media_id in ("321", "123", "124")
        ]
        relations = [
            AnimeRelation("321", "123", "sequel"),
            AnimeRelation("123", "124", "sequel"),
        ]
        nodes_by_media_id = {node.media_id: node for node in nodes}
        final_snapshot = AnimeFranchiseSnapshot(
            root_node=nodes_by_media_id["321"],
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=relations,
            continuity_component=nodes,
            series_line=nodes,
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="321",
            canonical_root_media_id="321",
        )
        final_snapshot_service = Mock()
        final_snapshot_service.build.return_value = final_snapshot

        AnimeSeriesViewProjectionRefreshService(
            snapshot_service=final_snapshot_service
        ).refresh_for_media_ids(
            user=self.user,
            media_ids={"321"},
        )

        self.assertEqual(
            set(
                AnimeSeriesViewMembership.objects.filter(
                    user=self.user,
                    media_id__in={"123", "124"},
                ).values_list("media_id", flat=True)
            ),
            {"123", "124"},
        )

    def test_batch_refresh_reanchors_satellite_and_avoids_partial_split(self):
        for media_id, title in (("123", "Season 2"), ("124", "Movie")):
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=title,
                image=f"https://example.com/{media_id}.jpg",
            )
            anime = Anime(
                user=self.user,
                item=item,
                status=Status.PLANNING.value,
            )
            anime._skip_hot_priority = True
            with patch.object(Item, "fetch_releases"):
                anime.save()

        initial_nodes = [
            AnimeNode(
                media_id="124",
                title="Movie",
                source="mal",
                media_type="movie",
                image="https://example.com/124.jpg",
                start_date=None,
            ),
            AnimeNode(
                media_id="123",
                title="Season 2",
                source="mal",
                media_type="tv",
                image="https://example.com/123.jpg",
                start_date=None,
            ),
        ]
        initial_by_id = {node.media_id: node for node in initial_nodes}
        initial_snapshot = AnimeFranchiseSnapshot(
            root_node=initial_by_id["124"],
            nodes_by_media_id=initial_by_id,
            all_normalized_relations=[
                AnimeRelation("124", "123", "parent_story"),
                AnimeRelation("123", "321", "prequel"),
            ],
            continuity_component=initial_nodes,
            series_line=[],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=False,
            fallback_anchor_media_id="124",
            canonical_root_media_id="124",
        )

        complete_nodes = [
            AnimeNode(
                media_id=media_id,
                title=title,
                source="mal",
                media_type=media_type,
                image=f"https://example.com/{media_id}.jpg",
                start_date=None,
            )
            for media_id, title, media_type in (
                ("321", "Season 1", "tv"),
                ("123", "Season 2", "tv"),
                ("124", "Movie", "movie"),
            )
        ]
        complete_by_id = {node.media_id: node for node in complete_nodes}
        complete_snapshot = AnimeFranchiseSnapshot(
            root_node=complete_by_id["321"],
            nodes_by_media_id=complete_by_id,
            all_normalized_relations=[
                AnimeRelation("321", "123", "sequel"),
                AnimeRelation("123", "124", "side_story"),
                AnimeRelation("124", "123", "parent_story"),
            ],
            continuity_component=complete_nodes,
            series_line=[complete_by_id["321"], complete_by_id["123"]],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="321",
            canonical_root_media_id="321",
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = lambda media_id, **_kwargs: {
            "124": initial_snapshot,
            "123": complete_snapshot,
            "321": complete_snapshot,
        }[media_id]

        stats = AnimeSeriesViewProjectionRefreshService(
            snapshot_service=snapshot_service
        ).refresh_for_media_ids(
            user=self.user,
            media_ids={"124", "321"},
        )

        memberships = list(
            AnimeSeriesViewMembership.objects.filter(
                user=self.user,
                media_id__in={"321", "123", "124"},
            ).order_by("media_id")
        )
        self.assertEqual(stats.snapshots_refreshed, 1)
        self.assertEqual(stats.snapshots_skipped, 1)
        self.assertEqual({row.root_media_id for row in memberships}, {"321"})
        self.assertEqual({row.component_size for row in memberships}, {3})
        self.assertEqual({row.projection_version for row in memberships}, {"v2"})
