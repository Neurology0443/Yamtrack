# ruff: noqa: D101,D102,D107
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_import_profiles import (
    CompleteImportProfile,
    ContinuityImportProfile,
    SeedMode,
    SatellitesImportProfile,
)
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


class AnimeFranchiseImportProfilesTests(SimpleTestCase):
    def setUp(self):
        self.nodes = {
            "1": AnimeNode("1", "S1", "mal", "tv", "img", date(2020, 1, 1), []),
            "2": AnimeNode("2", "S2", "mal", "tv", "img", date(2021, 1, 1), []),
            "3": AnimeNode("3", "Movie", "mal", "movie", "img", date(2021, 6, 1), [], 24, 13),
            "4": AnimeNode("4", "CM", "mal", "cm", "img", date(2021, 7, 1), []),
        }
        self.snapshot = AnimeFranchiseSnapshot(
            root_node=self.nodes["2"],
            nodes_by_media_id=self.nodes,
            all_normalized_relations=[],
            continuity_component=[self.nodes["1"], self.nodes["2"], self.nodes["4"]],
            series_line=[self.nodes["1"], self.nodes["2"]],
            direct_anchors=[self.nodes["1"], self.nodes["2"]],
            direct_candidates=[AnimeRelation("1", "3", "spin_off"), AnimeRelation("2", "4", "other")],
            has_series_line=True,
            fallback_anchor_media_id="2",
            canonical_root_media_id="1",
            promoted_continuity_candidates=[],
        )

    def test_continuity_profile_filters_noise(self):
        selection = ContinuityImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2"})

    def test_continuity_profile_excludes_summary_targets(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Recap Target", "mal", "tv", "img", date(2021, 1, 1), [], 24),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[AnimeRelation("10", "20", "summary")],
            continuity_component=[nodes["10"], nodes["20"]],
            series_line=[nodes["10"], nodes["20"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = ContinuityImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"10"})

    def test_continuity_profile_keeps_non_summary_node(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Normal Continuity", "mal", "tv", "img", date(2021, 1, 1), [], 24),
            "30": AnimeNode("30", "Other Relation Target", "mal", "movie", "img", date(2022, 1, 1), [], 24),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[AnimeRelation("10", "30", "spin_off")],
            continuity_component=[nodes["10"], nodes["20"]],
            series_line=[nodes["10"], nodes["20"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = ContinuityImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"10", "20"})

    def test_continuity_profile_excludes_summary_target_even_if_on_continuity_path(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Sequel + Summary Target", "mal", "tv", "img", date(2021, 1, 1), [], 24),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[
                AnimeRelation("10", "20", "sequel"),
                AnimeRelation("10", "20", "summary"),
            ],
            continuity_component=[nodes["10"], nodes["20"]],
            series_line=[nodes["10"], nodes["20"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = ContinuityImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"10"})

    def _continuity_snapshot_for_runtime(self, target_node: AnimeNode) -> AnimeFranchiseSnapshot:
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            target_node.media_id: target_node,
        }
        return AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"], target_node],
            series_line=[nodes["10"], target_node],
            direct_anchors=[nodes["10"]],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

    def test_continuity_profile_keeps_runtime_above_15_minutes(self):
        target = AnimeNode(
            "20",
            "Long Enough",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
        )
        selection = ContinuityImportProfile().select(
            self._continuity_snapshot_for_runtime(target)
        )
        self.assertEqual(selection.media_ids, {"10", "20"})

    def test_continuity_profile_excludes_runtime_below_15_minutes(self):
        target = AnimeNode(
            "20",
            "Too Short",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=10,
        )
        selection = ContinuityImportProfile().select(
            self._continuity_snapshot_for_runtime(target)
        )
        self.assertEqual(selection.media_ids, {"10"})

    def test_continuity_profile_excludes_runtime_equal_15_minutes(self):
        target = AnimeNode(
            "20",
            "Boundary Short",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=15,
        )
        selection = ContinuityImportProfile().select(
            self._continuity_snapshot_for_runtime(target)
        )
        self.assertEqual(selection.media_ids, {"10"})

    def test_continuity_profile_keeps_unknown_runtime(self):
        target = AnimeNode(
            "20",
            "Unknown Runtime",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=None,
        )
        selection = ContinuityImportProfile().select(
            self._continuity_snapshot_for_runtime(target)
        )
        self.assertEqual(selection.media_ids, {"10", "20"})

    def test_continuity_profile_keeps_cm_pv_excluded_regardless_of_runtime(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "CM Long", "mal", "cm", "img", date(2021, 1, 1), [], 24),
            "21": AnimeNode("21", "PV Unknown", "mal", "pv", "img", date(2021, 1, 1), [], None),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"], nodes["20"], nodes["21"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = ContinuityImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"10"})

    def test_satellites_profile_uses_direct_candidates(self):
        selection = SatellitesImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"3"})

    def test_satellites_profile_remains_direct_only_when_ui_promoted_continuity_exists(self):
        nodes = {
            "10": AnimeNode("10", "Season 1", "mal", "tv", "img", date(2020, 1, 1), []),
            "20": AnimeNode("20", "Satellite", "mal", "movie", "img", date(2021, 1, 1), [], 24, 13),
            "21": AnimeNode("21", "Promoted only", "mal", "movie", "img", date(2022, 1, 1), [], 24, 13),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", "20", "spin_off")],
            promoted_continuity_candidates=[
                AnimeRelation("10", "20", "sequel"),
                AnimeRelation("20", "21", "sequel"),
            ],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_filters_relation_types(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Spin-off", "mal", "movie", "img", date(2021, 1, 1), [], 24),
            "21": AnimeNode("21", "Alt", "mal", "movie", "img", date(2021, 6, 1), [], 24),
            "22": AnimeNode("22", "Side Story", "mal", "movie", "img", date(2022, 1, 1), [], 24),
            "23": AnimeNode("23", "Parent Story", "mal", "movie", "img", date(2022, 6, 1), [], 24),
            "24": AnimeNode("24", "Summary", "mal", "movie", "img", date(2022, 8, 1), [], 24),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[
                AnimeRelation("10", "20", "spin_off"),
                AnimeRelation("10", "21", "alternative_version"),
                AnimeRelation("10", "22", "side_story"),
                AnimeRelation("10", "23", "parent_story"),
                AnimeRelation("10", "24", "summary"),
            ],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20", "21", "22"})
        self.assertNotIn("23", selection.media_ids)
        self.assertNotIn("24", selection.media_ids)

    def test_satellites_profile_excludes_runtime_below_15_minutes(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Short", "mal", "movie", "img", date(2021, 1, 1), [], 10),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", "20", "spin_off")],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, set())

    def _snapshot_with_single_satellite_node(self, target_node: AnimeNode) -> AnimeFranchiseSnapshot:
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            target_node.media_id: target_node,
        }
        return AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", target_node.media_id, "spin_off")],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

    def test_satellites_profile_keeps_13_episodes_24_minutes(self):
        target = AnimeNode(
            "20",
            "Standard Season",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
            episode_count=13,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_keeps_single_episode_76_minutes(self):
        target = AnimeNode(
            "20",
            "Long Special",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=76,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_excludes_12_episodes_3_minutes(self):
        target = AnimeNode(
            "20",
            "Shorts",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=3,
            episode_count=12,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_excludes_single_episode_24_minutes(self):
        target = AnimeNode(
            "20",
            "Short One-Shot",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_excludes_single_episode_30_minutes(self):
        target = AnimeNode(
            "20",
            "Boundary One-Shot",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=30,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_keeps_two_episodes_30_minutes(self):
        target = AnimeNode(
            "20",
            "Boundary Two Episodes",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=30,
            episode_count=2,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_excludes_tv_special_with_unknown_runtime(self):
        target = AnimeNode(
            "20",
            "TV Special Unknown Runtime",
            "mal",
            "tv_special",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=None,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_excludes_tv_special_with_runtime_15_and_single_episode(self):
        target = AnimeNode(
            "20",
            "TV Special Threshold",
            "mal",
            "tv_special",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=15,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_keeps_tv_special_with_runtime_16_and_single_episode(self):
        target = AnimeNode(
            "20",
            "TV Special Above Threshold",
            "mal",
            "tv_special",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=16,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_excludes_non_tv_special_with_runtime_10_and_single_episode(self):
        target = AnimeNode(
            "20",
            "Non Special Short",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=10,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_excludes_non_tv_special_with_runtime_24_and_single_episode(self):
        target = AnimeNode(
            "20",
            "Non Special One-Shot",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_keeps_non_tv_special_with_runtime_24_and_13_episodes(self):
        target = AnimeNode(
            "20",
            "Non Special Season",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
            episode_count=13,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_keeps_non_tv_special_with_runtime_76_and_single_episode(self):
        target = AnimeNode(
            "20",
            "Non Special Long One-Shot",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=76,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_rejects_unknown_runtime(self):
        target = AnimeNode(
            "20",
            "Unknown Runtime",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=None,
            episode_count=1,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, set())

    def test_satellites_profile_keeps_unknown_episode_count_with_24_runtime(self):
        target = AnimeNode(
            "20",
            "Unknown Episodes",
            "mal",
            "movie",
            "img",
            date(2021, 1, 1),
            [],
            runtime_minutes=24,
            episode_count=None,
        )
        selection = SatellitesImportProfile().select(
            self._snapshot_with_single_satellite_node(target)
        )
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_keeps_runtime_15_when_episode_count_is_unknown(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Edge", "mal", "movie", "img", date(2021, 1, 1), [], 15),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", "20", "side_story")],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20"})

    def test_satellites_profile_is_direct_only(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), []),
            "20": AnimeNode("20", "Direct", "mal", "movie", "img", date(2021, 1, 1), [], 24, 13),
            "30": AnimeNode("30", "Indirect", "mal", "movie", "img", date(2022, 1, 1), [], 24, 13),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[
                AnimeRelation("10", "20", "spin_off"),
                AnimeRelation("20", "30", "spin_off"),
            ],
            continuity_component=[nodes["10"]],
            series_line=[nodes["10"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", "20", "spin_off")],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20"})
        self.assertNotIn("30", selection.media_ids)

    def test_complete_profile_unions_with_dedup(self):
        selection = CompleteImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2", "3"})

    def test_complete_profile_uses_filtered_continuity_plus_unchanged_satellites(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), [], 24),
            "20": AnimeNode("20", "Short Continuity", "mal", "tv", "img", date(2021, 1, 1), [], 10),
            "30": AnimeNode("30", "Satellite", "mal", "movie", "img", date(2022, 1, 1), [], 24, 13),
        }
        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["10"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["10"], nodes["20"]],
            series_line=[nodes["10"], nodes["20"]],
            direct_anchors=[nodes["10"]],
            direct_candidates=[AnimeRelation("10", "30", "spin_off")],
            has_series_line=True,
            fallback_anchor_media_id="10",
            canonical_root_media_id="10",
            promoted_continuity_candidates=[],
        )

        selection = CompleteImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"10", "30"})

    def test_seed_mode_values_are_typed(self):
        self.assertEqual(ContinuityImportProfile.seed_mode, SeedMode.ALL_LIBRARY)
        self.assertEqual(SatellitesImportProfile.seed_mode, SeedMode.CANONICAL_ONLY)

    def test_invalid_seed_mode_raises_explicit_error(self):
        class InvalidSeedProfile(ContinuityImportProfile):
            seed_mode = "unexpected_mode"
            key = "invalid"

        with self.assertRaisesMessage(
            ValueError,
            "Unsupported seed_mode 'unexpected_mode' for profile 'invalid'.",
        ):
            InvalidSeedProfile().is_seed_eligible(
                seed_mal_id="1",
                known_canonical_root="1",
            )
