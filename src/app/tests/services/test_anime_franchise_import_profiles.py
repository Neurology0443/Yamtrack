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
            "3": AnimeNode("3", "Movie", "mal", "movie", "img", date(2021, 6, 1), []),
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
        )

    def test_continuity_profile_filters_noise(self):
        selection = ContinuityImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2"})

    def test_satellites_profile_uses_direct_candidates(self):
        selection = SatellitesImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"3"})

    def test_satellites_profile_filters_relation_types(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), []),
            "20": AnimeNode("20", "Spin-off", "mal", "movie", "img", date(2021, 1, 1), []),
            "21": AnimeNode("21", "Alt", "mal", "movie", "img", date(2021, 6, 1), []),
            "22": AnimeNode("22", "Side Story", "mal", "movie", "img", date(2022, 1, 1), []),
            "23": AnimeNode("23", "Parent Story", "mal", "movie", "img", date(2022, 6, 1), []),
            "24": AnimeNode("24", "Summary", "mal", "movie", "img", date(2022, 8, 1), []),
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
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20", "21", "22", "23"})
        self.assertNotIn("24", selection.media_ids)

    def test_satellites_profile_is_direct_only(self):
        nodes = {
            "10": AnimeNode("10", "Main", "mal", "tv", "img", date(2020, 1, 1), []),
            "20": AnimeNode("20", "Direct", "mal", "movie", "img", date(2021, 1, 1), []),
            "30": AnimeNode("30", "Indirect", "mal", "movie", "img", date(2022, 1, 1), []),
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
        )

        selection = SatellitesImportProfile().select(snapshot)
        self.assertEqual(selection.media_ids, {"20"})
        self.assertNotIn("30", selection.media_ids)

    def test_complete_profile_unions_with_dedup(self):
        selection = CompleteImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2", "3"})

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
