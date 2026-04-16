# ruff: noqa: D101,D102,D107
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_import_profiles import (
    CompleteImportProfile,
    ContinuityImportProfile,
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
        )

    def test_continuity_profile_filters_noise(self):
        selection = ContinuityImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2"})

    def test_satellites_profile_uses_direct_candidates(self):
        selection = SatellitesImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"3"})

    def test_complete_profile_unions_with_dedup(self):
        selection = CompleteImportProfile().select(self.snapshot)
        self.assertEqual(selection.media_ids, {"1", "2", "3"})
