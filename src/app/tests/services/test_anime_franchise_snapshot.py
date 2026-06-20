# ruff: noqa: D101,D102,D107,ARG002,ARG005,FBT002
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_snapshot import (
    AnimeBranchRelation,
    AnimeFranchiseSnapshotService,
)
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


class FakeGraphBuilder:
    def __init__(self, nodes, build_media_ids=None):
        self.nodes = nodes
        self.build_media_ids = build_media_ids

    def build(self, root_media_id):
        if self.build_media_ids is not None:
            return {
                media_id: self.nodes[media_id]
                for media_id in self.build_media_ids
            }
        return self.nodes

    def get_direct_neighbors(self, media_id):
        return self.nodes[str(media_id)].relations

    def ensure_node(self, media_id):
        return self.nodes[str(media_id)]

    @property
    def _node_cache(self):
        return self.nodes


class AnimeFranchiseSnapshotServiceTests(SimpleTestCase):
    def _build_branch_snapshot(
        self,
        *,
        nodes,
        root_media_id,
        build_media_ids=None,
    ):
        return AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes, build_media_ids)
        ).build(root_media_id)

    def test_branch_relation_orients_progressive_edge_exposed_from_branch(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "SAO",
                "mal",
                "tv",
                "img",
                date(2012, 7, 8),
                [AnimeRelation("100", "101", "sequel")],
            ),
            "101": AnimeNode(
                "101",
                "SAO II",
                "mal",
                "tv",
                "img",
                date(2014, 7, 5),
                [],
            ),
            "42916": AnimeNode(
                "42916",
                "Progressive",
                "mal",
                "movie",
                "img",
                date(2021, 10, 30),
                [AnimeRelation("42916", "100", "alternative_version")],
            ),
        }

        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="42916",
        )

        self.assertEqual(
            snapshot.branch_relations,
            [AnimeBranchRelation("100", "42916", "alternative_version")],
        )

    def test_branch_relation_orients_progressive_edge_exposed_from_main(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "SAO",
                "mal",
                "tv",
                "img",
                date(2012, 7, 8),
                [
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "42916", "alternative_version"),
                ],
            ),
            "101": AnimeNode(
                "101",
                "SAO II",
                "mal",
                "tv",
                "img",
                date(2014, 7, 5),
                [],
            ),
            "42916": AnimeNode(
                "42916",
                "Progressive",
                "mal",
                "movie",
                "img",
                date(2021, 10, 30),
                [],
            ),
        }

        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="100",
        )

        self.assertEqual(
            snapshot.branch_relations,
            [AnimeBranchRelation("100", "42916", "alternative_version")],
        )

    def test_branch_relation_orients_reverse_konosuba_spin_off_from_branch_root(
        self,
    ):
        nodes = {
            "30831": AnimeNode(
                "30831",
                "KonoSuba",
                "mal",
                "tv",
                "img",
                date(2016, 1, 14),
                [],
            ),
            "51958": AnimeNode(
                "51958",
                "Bakuen",
                "mal",
                "tv",
                "img",
                date(2023, 4, 6),
                [
                    AnimeRelation("51958", "30831", "spin_off"),
                    AnimeRelation("51958", "57833", "sequel"),
                ],
            ),
            "57833": AnimeNode(
                "57833",
                "Bakuen 2",
                "mal",
                "tv",
                "img",
                date(2026, 1, 1),
                [],
            ),
        }
        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="51958",
        )

        self.assertEqual(
            snapshot.branch_relations,
            [AnimeBranchRelation("30831", "51958", "spin_off")],
        )

    def test_branch_relation_orients_konosuba_spin_off_from_main_root(self):
        nodes = {
            "30831": AnimeNode(
                "30831",
                "KonoSuba",
                "mal",
                "tv",
                "img",
                date(2016, 1, 14),
                [AnimeRelation("30831", "51958", "spin_off")],
            ),
            "51958": AnimeNode(
                "51958",
                "Bakuen",
                "mal",
                "tv",
                "img",
                date(2023, 4, 6),
                [AnimeRelation("51958", "57833", "sequel")],
            ),
            "57833": AnimeNode(
                "57833",
                "Bakuen 2",
                "mal",
                "tv",
                "img",
                date(2026, 1, 1),
                [],
            ),
        }
        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="30831",
            build_media_ids={"30831"},
        )

        self.assertEqual(
            snapshot.branch_relations,
            [AnimeBranchRelation("30831", "51958", "spin_off")],
        )

    def test_branch_relation_orients_alternative_setting_from_either_root(self):
        nodes = {
            "1": AnimeNode("1", "Main", "mal", "tv", "img", None, []),
            "2": AnimeNode(
                "2",
                "Alternative",
                "mal",
                "movie",
                "img",
                None,
                [AnimeRelation("2", "1", "alternative_setting")],
            ),
        }
        branch_snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="2",
        )
        main_snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="1",
        )

        self.assertEqual(
            branch_snapshot.branch_relations,
            [AnimeBranchRelation("1", "2", "alternative_setting")],
        )
        self.assertEqual(
            main_snapshot.branch_relations,
            [AnimeBranchRelation("1", "2", "alternative_setting")],
        )

    def test_branch_relations_are_empty_when_both_components_are_parent_anchors(
        self,
    ):
        nodes = {
            "1": AnimeNode(
                "1",
                "One",
                "mal",
                "tv",
                "img",
                None,
                [AnimeRelation("1", "2", "alternative_version")],
            ),
            "2": AnimeNode("2", "Two", "mal", "tv", "img", None, []),
            "3": AnimeNode("3", "Root", "mal", "movie", "img", None, []),
        }
        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="3",
        )

        self.assertEqual(snapshot.branch_relations, [])

    def test_branch_relations_are_empty_without_parent_anchor_component(self):
        nodes = {
            "1": AnimeNode(
                "1",
                "One",
                "mal",
                "movie",
                "img",
                None,
                [AnimeRelation("1", "2", "alternative_version")],
            ),
            "2": AnimeNode("2", "Two", "mal", "movie", "img", None, []),
            "3": AnimeNode("3", "Root", "mal", "movie", "img", None, []),
        }
        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="3",
        )

        self.assertEqual(snapshot.branch_relations, [])

    def test_topological_series_order_ignores_branch_relations(self):
        nodes = {
            "1": AnimeNode(
                "1",
                "Main",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("1", "3", "sequel")],
            ),
            "2": AnimeNode(
                "2",
                "Spin-off",
                "mal",
                "tv",
                "img",
                date(2030, 1, 1),
                [AnimeRelation("2", "1", "spin_off")],
            ),
            "3": AnimeNode(
                "3",
                "Main sequel",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [],
            ),
        }

        snapshot = self._build_branch_snapshot(
            nodes=nodes,
            root_media_id="1",
        )

        self.assertEqual(
            [node.media_id for node in snapshot.series_line],
            ["1", "3", "2"],
        )

    def test_series_line_tv_only_and_deterministic(self):
        nodes = {
            "10": AnimeNode(
                "10",
                "S1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("10", "20", "sequel")],
            ),
            "20": AnimeNode(
                "20",
                "S2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [
                    AnimeRelation("20", "10", "prequel"),
                    AnimeRelation("20", "30", "sequel"),
                ],
            ),
            "30": AnimeNode("30", "Movie", "mal", "movie", "img", date(2022, 1, 1), []),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes)
        ).build("20")
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
        self.assertEqual(
            [rel.target_media_id for rel in snapshot.direct_candidates], ["501"]
        )
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
                [
                    AnimeRelation("200", "100", "prequel"),
                    AnimeRelation("200", "300", "sequel"),
                ],
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

    def test_root_story_parent_full_story_to_tv_is_hydrated(self):
        root = AnimeNode(
            "27891",
            "Debriefing",
            "mal",
            "special",
            "img",
            date(2014, 1, 1),
            [AnimeRelation("27891", "100", "full_story")],
        )
        parent = AnimeNode("100", "SAO II", "mal", "tv", "img", date(2014, 7, 1), [])

        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder({"27891": root, "100": parent})
        ).build("27891")

        self.assertIn("100", snapshot.nodes_by_media_id)
        self.assertIn(
            AnimeRelation("27891", "100", "full_story"),
            snapshot.root_story_parent_candidates,
        )

    def test_root_story_parent_ignores_tv_root(self):
        root = AnimeNode(
            "100",
            "SAO II",
            "mal",
            "tv",
            "img",
            date(2014, 7, 1),
            [AnimeRelation("100", "27891", "full_story")],
        )
        recap = AnimeNode(
            "27891", "Debriefing", "mal", "special", "img", date(2014, 1, 1), []
        )

        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder({"100": root, "27891": recap})
        ).build("100")

        self.assertEqual(snapshot.root_story_parent_candidates, [])

    def test_root_story_parent_ignores_non_tv_target(self):
        root = AnimeNode(
            "27891",
            "Debriefing",
            "mal",
            "special",
            "img",
            date(2014, 1, 1),
            [AnimeRelation("27891", "200", "full_story")],
        )
        movie = AnimeNode("200", "Movie", "mal", "movie", "img", date(2014, 7, 1), [])

        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder({"27891": root, "200": movie})
        ).build("27891")

        self.assertEqual(snapshot.root_story_parent_candidates, [])

    def test_root_story_parent_ignores_missing_target(self):
        class MissingTargetGraphBuilder(FakeGraphBuilder):
            def ensure_node(self, media_id):
                if str(media_id) == "100":
                    return None
                return super().ensure_node(media_id)

        root = AnimeNode(
            "27891",
            "Debriefing",
            "mal",
            "special",
            "img",
            date(2014, 1, 1),
            [AnimeRelation("27891", "100", "full_story")],
        )

        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=MissingTargetGraphBuilder({"27891": root})
        ).build("27891")

        self.assertEqual(snapshot.root_story_parent_candidates, [])

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
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
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

        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata
        )
        node = builder.ensure_node("40")

        self.assertEqual(node.episode_count, 13)

    def test_non_series_line_root_is_included_in_direct_anchors(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "TV",
                "mal",
                "tv",
                "img",
                date(2011, 1, 1),
                [AnimeRelation("100", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [
                    AnimeRelation("200", "300", "sequel"),
                    AnimeRelation("200", "100", "prequel"),
                ],
            ),
            "300": AnimeNode(
                "300",
                "Movie",
                "mal",
                "movie",
                "img",
                date(2011, 3, 1),
                [AnimeRelation("300", "200", "prequel")],
            ),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes)
        ).build("200")

        self.assertEqual([node.media_id for node in snapshot.series_line], ["100"])
        self.assertEqual(
            [node.media_id for node in snapshot.direct_anchors], ["100", "200"]
        )

    def test_special_root_can_surface_its_direct_continuity_neighbor(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "TV",
                "mal",
                "tv",
                "img",
                date(2011, 1, 1),
                [AnimeRelation("100", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [
                    AnimeRelation("200", "300", "sequel"),
                    AnimeRelation("200", "100", "prequel"),
                ],
            ),
            "300": AnimeNode(
                "300",
                "Movie",
                "mal",
                "movie",
                "img",
                date(2011, 3, 1),
                [AnimeRelation("300", "200", "prequel")],
            ),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes)
        ).build("200")

        self.assertEqual(
            {
                (rel.source_media_id, rel.target_media_id, rel.relation_type)
                for rel in snapshot.direct_candidates
            },
            {("100", "200", "sequel"), ("200", "300", "sequel")},
        )

    def test_series_line_root_behavior_does_not_over_expand(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "TV",
                "mal",
                "tv",
                "img",
                date(2011, 1, 1),
                [AnimeRelation("100", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Special",
                "mal",
                "special",
                "img",
                date(2011, 2, 1),
                [
                    AnimeRelation("200", "300", "sequel"),
                    AnimeRelation("200", "100", "prequel"),
                ],
            ),
            "300": AnimeNode(
                "300",
                "Movie",
                "mal",
                "movie",
                "img",
                date(2011, 3, 1),
                [AnimeRelation("300", "200", "prequel")],
            ),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes)
        ).build("100")

        self.assertEqual([node.media_id for node in snapshot.direct_anchors], ["100"])
        self.assertEqual(
            [
                (rel.source_media_id, rel.target_media_id, rel.relation_type)
                for rel in snapshot.direct_candidates
            ],
            [("100", "200", "sequel")],
        )

    def test_series_root_promotes_transitive_non_tv_continuity_chain_for_ui(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Season 1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("100", "101", "sequel")],
            ),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [
                    AnimeRelation("101", "100", "prequel"),
                    AnimeRelation("101", "200", "sequel"),
                ],
            ),
            "200": AnimeNode(
                "200",
                "Movie 1",
                "mal",
                "movie",
                "img",
                date(2022, 1, 1),
                [
                    AnimeRelation("200", "101", "prequel"),
                    AnimeRelation("200", "201", "sequel"),
                ],
            ),
            "201": AnimeNode(
                "201",
                "Movie 2",
                "mal",
                "movie",
                "img",
                date(2023, 1, 1),
                [
                    AnimeRelation("201", "200", "prequel"),
                    AnimeRelation("201", "202", "sequel"),
                ],
            ),
            "202": AnimeNode(
                "202",
                "Movie 3",
                "mal",
                "movie",
                "img",
                date(2024, 1, 1),
                [AnimeRelation("202", "201", "prequel")],
            ),
        }
        snapshot = AnimeFranchiseSnapshotService(
            graph_builder=FakeGraphBuilder(nodes)
        ).build("101")

        self.assertEqual(
            [node.media_id for node in snapshot.series_line], ["100", "101"]
        )
        self.assertEqual(
            [
                (rel.source_media_id, rel.target_media_id, rel.relation_type)
                for rel in snapshot.direct_candidates
            ],
            [("101", "200", "sequel")],
        )
        promoted_targets = {
            rel.target_media_id for rel in snapshot.promoted_continuity_candidates
        }
        self.assertEqual(promoted_targets, {"200", "201", "202"})

    def test_no_series_line_hydrates_deep_parent_story_secondary_candidate(self):
        metadata_map = self._break_time_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
        )

        snapshot = AnimeFranchiseSnapshotService(graph_builder=builder).build("33569")

        self.assertFalse(snapshot.has_series_line)
        self.assertIn("99999", snapshot.nodes_by_media_id)
        self.assertIn(
            AnimeRelation("63830", "99999", "parent_story"),
            snapshot.no_series_line_secondary_candidates,
        )
        self.assertNotIn(
            "99999",
            [node.media_id for node in snapshot.continuity_component],
        )

    def test_no_series_line_secondary_candidates_ignored_when_series_line_exists(self):
        metadata_map = self._break_time_metadata_map(media_type="tv")
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
        )

        snapshot = AnimeFranchiseSnapshotService(graph_builder=builder).build("33569")

        self.assertTrue(snapshot.has_series_line)
        self.assertEqual(snapshot.no_series_line_secondary_candidates, [])

    def test_no_series_line_secondary_candidate_respects_max_nodes(self):
        metadata_map = self._break_time_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=5,
        )

        snapshot = AnimeFranchiseSnapshotService(graph_builder=builder).build("33569")

        self.assertNotIn("99999", snapshot.nodes_by_media_id)
        self.assertEqual(snapshot.no_series_line_secondary_candidates, [])
        self.assertTrue(builder.truncated)

    @staticmethod
    def _break_time_metadata_map(media_type="special"):
        def node(media_id, title, start_date, related):
            return {
                "media_id": media_id,
                "title": title,
                "source": "mal",
                "details": {"raw_media_type": media_type, "start_date": start_date},
                "image": f"img-{media_id}",
                "related": {
                    "related_anime": [
                        {"media_id": target_id, "relation_type": relation_type}
                        for target_id, relation_type in related
                    ]
                },
            }

        return {
            "33142": node("33142", "Break Time", "2016-04-08", [("33569", "sequel")]),
            "33569": node(
                "33569",
                "Re:Petit",
                "2016-06-24",
                [("33142", "prequel"), ("42364", "sequel")],
            ),
            "42364": node("42364", "Break Time 2", "2020-07-10", [("60012", "sequel")]),
            "60012": node("60012", "Break Time 3", "2024-10-02", [("63830", "sequel")]),
            "63830": node(
                "63830", "Break Time 4", "2025-07-01", [("99999", "parent_story")]
            ),
            "99999": node("99999", "Re:Zero S4", "2026-01-01", []),
        }


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

    def test_graph_builder_truncates_at_max_nodes_without_exception(self):
        metadata_map = {
            "100": {
                "media_id": "100",
                "title": "S1",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2020-01-01"},
                "image": "s1",
                "related": {
                    "related_anime": [{"media_id": "200", "relation_type": "sequel"}]
                },
            },
            "200": {
                "media_id": "200",
                "title": "S2",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2021-01-01"},
                "image": "s2",
                "related": {
                    "related_anime": [{"media_id": "300", "relation_type": "sequel"}]
                },
            },
            "300": {
                "media_id": "300",
                "title": "S3",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2022-01-01"},
                "image": "s3",
                "related": {"related_anime": []},
            },
        }
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=2,
        )

        graph = builder.build("100")

        self.assertEqual(set(graph), {"100", "200"})
        self.assertTrue(builder.truncated)
        self.assertEqual(builder.truncation_reason, "max_nodes")

    def test_direct_candidate_missing_from_node_limit_is_ignored(self):
        metadata_map = {
            "100": {
                "media_id": "100",
                "title": "S1",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2020-01-01"},
                "image": "img",
                "related": {
                    "related_anime": [
                        {"media_id": "200", "relation_type": "spin_off"},
                    ],
                },
            },
            "200": {
                "media_id": "200",
                "title": "Spin",
                "source": "mal",
                "details": {"raw_media_type": "movie", "start_date": "2021-01-01"},
                "image": "img",
                "related": {"related_anime": []},
            },
        }
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=1,
        )
        service = AnimeFranchiseSnapshotService(graph_builder=builder)

        snapshot = service.build("100")

        self.assertEqual(set(snapshot.nodes_by_media_id), {"100"})
        self.assertEqual(snapshot.direct_candidates, [])
        self.assertTrue(builder.truncated)
        self.assertEqual(builder.truncation_reason, "max_nodes")

    def test_graph_builder_max_nodes_zero_is_unlimited(self):
        metadata_map = self._chain_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=0,
        )

        graph = builder.build("100")

        self.assertEqual(set(graph), {"100", "200", "300"})
        self.assertFalse(builder.truncated)

    def test_graph_builder_max_nodes_negative_is_unlimited(self):
        metadata_map = self._chain_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=-1,
        )

        graph = builder.build("100")

        self.assertEqual(set(graph), {"100", "200", "300"})
        self.assertFalse(builder.truncated)

    def test_graph_builder_max_nodes_one_keeps_root(self):
        metadata_map = self._chain_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=1,
        )

        graph = builder.build("100")

        self.assertEqual(set(graph), {"100"})
        self.assertEqual(builder.node_count, 1)
        self.assertTrue(builder.truncated)
        self.assertEqual(builder.truncation_reason, "max_nodes")

    def test_ensure_node_returns_cached_node_even_when_limit_reached(self):
        metadata_map = self._chain_metadata_map()
        builder = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda media_id, refresh_cache=False: metadata_map[
                str(media_id)
            ],
            max_nodes=1,
        )
        graph = builder.build("100")

        self.assertIs(builder.ensure_node("100"), graph["100"])
        self.assertIsNone(builder.ensure_node("200"))
        self.assertTrue(builder.truncated)

    @staticmethod
    def _chain_metadata_map():
        return {
            "100": {
                "media_id": "100",
                "title": "S1",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2020-01-01"},
                "image": "s1",
                "related": {
                    "related_anime": [{"media_id": "200", "relation_type": "sequel"}]
                },
            },
            "200": {
                "media_id": "200",
                "title": "S2",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2021-01-01"},
                "image": "s2",
                "related": {
                    "related_anime": [{"media_id": "300", "relation_type": "sequel"}]
                },
            },
            "300": {
                "media_id": "300",
                "title": "S3",
                "source": "mal",
                "details": {"raw_media_type": "tv", "start_date": "2022-01-01"},
                "image": "s3",
                "related": {"related_anime": []},
            },
        }
