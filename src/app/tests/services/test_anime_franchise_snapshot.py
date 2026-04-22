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
        self.assertEqual(snapshot.canonical_root_media_id, "10")

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
        self.assertEqual(snapshot.canonical_root_media_id, "500")

    def test_continuity_from_intermediate_seed_is_transitive(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "S1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("100", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "S2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("200", "100", "prequel"), AnimeRelation("200", "300", "sequel")],
            ),
            "300": AnimeNode(
                "300",
                "S3",
                "mal",
                "tv",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("300", "200", "prequel")],
            ),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes),
        ).build("200")
        self.assertEqual(
            {node.media_id for node in snapshot.continuity_component},
            {"100", "200", "300"},
        )
        self.assertEqual(snapshot.canonical_root_media_id, "100")

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

    def test_graph_builder_maps_episode_count_from_metadata_details(self):
        metadata = {
            "media_id": "40",
            "title": "Episodes",
            "source": "mal",
            "details": {
                "raw_media_type": "tv",
                "start_date": "2022-01-01",
                "episodes": "13",
            },
            "image": "e",
            "related": {"related_anime": []},
        }

        builder = AnimeFranchiseGraphBuilder(metadata_fetcher=lambda media_id, refresh_cache=False: metadata)  # noqa: ARG005
        node = builder.ensure_node("40")

        self.assertEqual(node.episode_count, 13)

    def test_non_series_line_root_is_included_in_direct_anchors(self):
        nodes = {
            "100": AnimeNode("100", "TV", "mal", "tv", "img", date(2011, 1, 1), [AnimeRelation("100", "200", "sequel")]),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [AnimeRelation("200", "300", "sequel"), AnimeRelation("200", "100", "prequel")],
            ),
            "300": AnimeNode("300", "Movie", "mal", "movie", "img", date(2011, 3, 1), [AnimeRelation("300", "200", "prequel")]),
        }
        snapshot = AnimeFranchiseSnapshotService(graph_builder=FakeGraphBuilder(nodes)).build("200")

        self.assertEqual([node.media_id for node in snapshot.series_line], ["100"])
        self.assertEqual([node.media_id for node in snapshot.direct_anchors], ["100", "200"])

    def test_special_root_can_surface_its_direct_continuity_neighbor(self):
        nodes = {
            "100": AnimeNode("100", "TV", "mal", "tv", "img", date(2011, 1, 1), [AnimeRelation("100", "200", "sequel")]),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [AnimeRelation("200", "300", "sequel"), AnimeRelation("200", "100", "prequel")],
            ),
            "300": AnimeNode("300", "Movie", "mal", "movie", "img", date(2011, 3, 1), [AnimeRelation("300", "200", "prequel")]),
        }
        snapshot = AnimeFranchiseSnapshotService(graph_builder=FakeGraphBuilder(nodes)).build("200")

        self.assertEqual(
            {(rel.source_media_id, rel.target_media_id, rel.relation_type) for rel in snapshot.direct_candidates},
            {("100", "200", "sequel"), ("200", "300", "sequel")},
        )

    def test_series_line_root_behavior_does_not_over_expand(self):
        nodes = {
            "100": AnimeNode("100", "TV", "mal", "tv", "img", date(2011, 1, 1), [AnimeRelation("100", "200", "sequel")]),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [AnimeRelation("200", "300", "sequel"), AnimeRelation("200", "100", "prequel")],
            ),
            "300": AnimeNode("300", "Movie", "mal", "movie", "img", date(2011, 3, 1), [AnimeRelation("300", "200", "prequel")]),
        }
        snapshot = AnimeFranchiseSnapshotService(graph_builder=FakeGraphBuilder(nodes)).build("100")

        self.assertEqual([node.media_id for node in snapshot.direct_anchors], ["100"])
        self.assertEqual(
            [(rel.source_media_id, rel.target_media_id, rel.relation_type) for rel in snapshot.direct_candidates],
            [("100", "200", "sequel")],
        )

    def test_series_root_promotes_transitive_non_tv_continuity_chain_for_ui(self):
        nodes = {
            "100": AnimeNode("100", "Season 1", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "101", "sequel")]),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("101", "100", "prequel"), AnimeRelation("101", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Movie 1",
                "mal",
                "movie",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("200", "101", "prequel"), AnimeRelation("200", "201", "sequel")],
            ),
            "201": AnimeNode(
                "201",
                "Movie 2",
                "mal",
                "movie",
                "img",
                date(2023, 1, 1),
                [AnimeRelation("201", "200", "prequel"), AnimeRelation("201", "202", "sequel")],
            ),
            "202": AnimeNode("202", "Movie 3", "mal", "movie", "img", date(2024, 1, 1), [AnimeRelation("202", "201", "prequel")]),
        }
        snapshot = AnimeFranchiseSnapshotService(graph_builder=FakeGraphBuilder(nodes)).build("101")

        self.assertEqual([node.media_id for node in snapshot.series_line], ["100", "101"])
        self.assertEqual(
            [(rel.source_media_id, rel.target_media_id, rel.relation_type) for rel in snapshot.direct_candidates],
            [("101", "200", "sequel")],
        )
        promoted_targets = {rel.target_media_id for rel in snapshot.promoted_continuity_candidates}
        self.assertEqual(promoted_targets, {"200", "201", "202"})


class AnimeFranchiseGraphBuilderRuntimeParsingTests(SimpleTestCase):
    def test_parse_runtime_minutes_variants(self):
        parser = AnimeFranchiseGraphBuilder._parse_runtime_minutes

        self.assertEqual(parser("1h 16m"), 76)
        self.assertEqual(parser("1 hr. 16 min."), 76)
        self.assertEqual(parser("24 min"), 24)
        self.assertEqual(parser("24 min. per ep."), 24)
        self.assertEqual(parser("3 min"), 3)
        self.assertEqual(parser("3 min. per ep."), 3)

    def test_parse_runtime_minutes_returns_none_for_non_parsable_values(self):
        parser = AnimeFranchiseGraphBuilder._parse_runtime_minutes

        self.assertIsNone(parser(None))
        self.assertIsNone(parser(""))
        self.assertIsNone(parser("unknown"))
