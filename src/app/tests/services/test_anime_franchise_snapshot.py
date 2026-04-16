# ruff: noqa: D101,D102,D107
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


class FakeGraphBuilder:
    def __init__(self, nodes):
        self.nodes = nodes

    def build(self, root_media_id):
        return self.nodes

    def get_direct_neighbors(self, media_id):
        return self.nodes[str(media_id)].relations

    def ensure_node(self, media_id):
        return self.nodes[str(media_id)]

    @property
    def _node_cache(self):
        return self.nodes


class AnimeFranchiseSnapshotServiceTests(SimpleTestCase):
    def test_series_line_tv_only_and_deterministic(self):
        nodes = {
            "10": AnimeNode("10", "S1", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("10", "20", "sequel")]),
            "20": AnimeNode("20", "S2", "mal", "tv", "img", date(2021, 1, 1), [AnimeRelation("20", "10", "prequel"), AnimeRelation("20", "30", "sequel")]),
            "30": AnimeNode("30", "Movie", "mal", "movie", "img", date(2022, 1, 1), []),
        }
        snapshot = AnimeFranchiseSnapshotService(graph_builder=FakeGraphBuilder(nodes)).build("20")
        self.assertEqual([node.media_id for node in snapshot.series_line], ["10", "20"])

    def test_direct_anchors_and_fallback(self):
        movie_root = AnimeNode(
            "500",
            "Movie",
            "mal",
            "movie",
            "img",
            date(2020, 1, 1),
            [AnimeRelation("500", "501", "spin_off")],
        )
        spin_off = AnimeNode("501", "Spin", "mal", "movie", "img", date(2021, 1, 1), [])
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder({"500": movie_root, "501": spin_off})
        ).build("500")
        self.assertFalse(snapshot.has_series_line)
        self.assertEqual(snapshot.fallback_anchor_media_id, "500")
        self.assertEqual([node.media_id for node in snapshot.direct_anchors], ["500"])
        self.assertEqual([rel.target_media_id for rel in snapshot.direct_candidates], ["501"])

    def test_graph_cache_isolation_between_seeds(self):
        metadata_map = {
            "10": {
                "media_id": "10",
                "title": "A",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2020-01-01"},
                "image": "a",
                "related": {"related_anime": []},
            },
            "20": {
                "media_id": "20",
                "title": "B",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2021-01-01"},
                "image": "b",
                "related": {"related_anime": []},
            },
        }

        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[str(media_id)],  # noqa: ARG005
        )
        service = AnimeFranchiseSnapshotService(graph_builder=builder)
        snapshot_a = service.build("10")
        snapshot_b = service.build("20")

        self.assertEqual(set(snapshot_a.nodes_by_media_id), {"10"})
        self.assertEqual(set(snapshot_b.nodes_by_media_id), {"20"})

    def test_refresh_cache_propagates_to_graph_fetcher(self):
        calls = []
        metadata = {
            "media_id": "30",
            "title": "C",
            "source": "mal",
            "details": {"raw_media_type": "tv", "start_date": "2022-01-01"},
            "image": "c",
            "related": {"related_anime": []},
        }

        def fetcher(media_id, refresh_cache=False):  # noqa: ARG001
            calls.append(refresh_cache)
            return metadata

        service = AnimeFranchiseSnapshotService(
            graph_builder=AnimeFranchiseGraphBuilder(metadata_fetcher=fetcher),
        )
        service.build("30", refresh_cache=True)
        self.assertEqual(calls, [True])
