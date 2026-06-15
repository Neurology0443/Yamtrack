# ruff: noqa: D101, D102
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline
from app.services.anime_franchise_ui.actions import (
    ensure_section,
    set_section_hidden_if_empty,
    set_section_order,
    set_section_title,
)
from app.services.anime_franchise_ui.adapter import ViewModelAdapter
from app.services.anime_franchise_ui.assembler import UiCandidateAssembler
from app.services.anime_franchise_ui.candidates import UiCandidate
from app.services.anime_franchise_ui.engine import RulePipeline
from app.services.anime_franchise_ui.layout import LayoutCompiler
from app.services.anime_franchise_ui.predicates import (
    episode_count_eq,
    episode_count_gt,
    episode_count_gte,
    episode_count_lt,
    episode_count_lte,
    relation_type_is,
    run_once,
    runtime_minutes_eq,
    runtime_minutes_gt,
    runtime_minutes_gte,
    runtime_minutes_lt,
    runtime_minutes_lte,
)
from app.services.anime_franchise_ui.rule_types import (
    CompiledSection,
    Rule,
    RuleContext,
    RulePack,
    SectionDefinition,
)
from app.services.anime_franchise_ui.series import SeriesBuilder


class AnimeFranchiseUiPipelineTests(TestCase):
    def _snapshot(self):
        series_1 = AnimeNode(
            "100", "Season 1", "mal", "tv", "img-100", date(2020, 1, 1), []
        )
        series_2 = AnimeNode(
            "200", "Season 2", "mal", "tv", "img-200", date(2021, 1, 1), []
        )
        movie = AnimeNode(
            "300", "Movie", "mal", "movie", "img-300", date(2022, 1, 1), []
        )
        ova = AnimeNode("400", "OVA", "mal", "ova", "img-400", date(2021, 6, 1), [])

        direct_candidates = [
            AnimeRelation("200", "300", "side_story"),
            AnimeRelation("200", "300", "spin_off"),
            AnimeRelation("100", "400", "other"),
        ]

        nodes_by_media_id = {
            "100": series_1,
            "200": series_2,
            "300": movie,
            "400": ova,
        }

        return SimpleNamespace(
            root_node=series_2,
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=direct_candidates,
            continuity_component=[series_1, series_2, movie, ova],
            series_line=[series_1, series_2],
            direct_anchors=[series_1, series_2],
            direct_candidates=direct_candidates,
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="200",
            canonical_root_media_id="100",
        )

    def _snapshot_with_spin_off_candidate(
        self,
        *,
        media_type: str,
        episode_count: int | None,
        runtime_minutes: int | None,
    ):
        snapshot = self._snapshot()
        candidate = AnimeNode(
            "500",
            "Spin-off Candidate",
            "mal",
            media_type,
            "img-500",
            date(2023, 1, 1),
            [],
            runtime_minutes=runtime_minutes,
            episode_count=episode_count,
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "500": candidate}
        snapshot.direct_candidates = [AnimeRelation("200", "500", "spin_off")]
        snapshot.all_normalized_relations = snapshot.direct_candidates
        return snapshot

    def _assert_candidate_section(
        self, snapshot, *, expected_section: str, absent_section: str
    ):
        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        expected_entries = sections.get(expected_section, {"entries": []})["entries"]
        absent_entries = sections.get(absent_section, {"entries": []})["entries"]

        self.assertIn("500", [entry["media_id"] for entry in expected_entries])
        self.assertNotIn("500", [entry["media_id"] for entry in absent_entries])

    def test_pipeline_promotes_substantial_tv_spin_off_to_spin_offs(self):
        snapshot = self._snapshot_with_spin_off_candidate(
            media_type="tv",
            episode_count=12,
            runtime_minutes=24,
        )

        self._assert_candidate_section(
            snapshot,
            expected_section="spin_offs",
            absent_section="related_series",
        )

    def test_pipeline_keeps_short_tv_spin_off_in_related_series(self):
        snapshot = self._snapshot_with_spin_off_candidate(
            media_type="tv",
            episode_count=12,
            runtime_minutes=12,
        )

        self._assert_candidate_section(
            snapshot,
            expected_section="related_series",
            absent_section="spin_offs",
        )

    def test_pipeline_keeps_low_episode_tv_spin_off_in_related_series(self):
        snapshot = self._snapshot_with_spin_off_candidate(
            media_type="tv",
            episode_count=3,
            runtime_minutes=24,
        )

        self._assert_candidate_section(
            snapshot,
            expected_section="related_series",
            absent_section="spin_offs",
        )

    def test_pipeline_promotes_long_movie_spin_off_to_spin_offs(self):
        snapshot = self._snapshot_with_spin_off_candidate(
            media_type="movie",
            episode_count=1,
            runtime_minutes=90,
        )

        self._assert_candidate_section(
            snapshot,
            expected_section="spin_offs",
            absent_section="related_series",
        )

    def test_pipeline_keeps_short_movie_spin_off_in_related_series(self):
        snapshot = self._snapshot_with_spin_off_candidate(
            media_type="movie",
            episode_count=1,
            runtime_minutes=45,
        )

        self._assert_candidate_section(
            snapshot,
            expected_section="related_series",
            absent_section="spin_offs",
        )

    def test_series_builder_uses_fixed_key_and_title(self):
        snapshot = self._snapshot()
        block = SeriesBuilder().build(snapshot)

        self.assertEqual(block.key, "series")
        self.assertEqual(block.title, "Series")
        self.assertEqual([entry.media_id for entry in block.entries], ["100", "200"])
        self.assertTrue(block.entries[1].is_current)

    def test_candidate_assembler_excludes_series_and_deduplicates(self):
        snapshot = self._snapshot()
        candidates = UiCandidateAssembler().build(snapshot)

        self.assertEqual(
            {candidate.media_id for candidate in candidates}, {"300", "400"}
        )
        self.assertEqual(len(candidates), 2)

    def test_candidate_assembler_preserves_multi_origin_signals_for_same_media(self):
        snapshot = self._snapshot()
        candidates = UiCandidateAssembler().build(snapshot)
        movie_candidate = next(
            candidate for candidate in candidates if candidate.media_id == "300"
        )

        self.assertEqual(movie_candidate.relation_type, "side_story")
        self.assertEqual(movie_candidate.relation_types, ["side_story", "spin_off"])
        self.assertEqual(movie_candidate.source_media_ids, ["200"])
        self.assertTrue(movie_candidate.has_series_line_origin)
        self.assertTrue(movie_candidate.has_root_origin)
        self.assertFalse(movie_candidate.has_non_series_origin)
        self.assertEqual(movie_candidate.linked_series_line_media_id, "200")
        self.assertEqual(movie_candidate.linked_root_media_id, "200")
        self.assertEqual(
            movie_candidate.metadata["origins"],
            [
                {
                    "source_media_id": "200",
                    "relation_type": "side_story",
                    "is_from_series_line": True,
                    "is_from_root_node": True,
                },
                {
                    "source_media_id": "200",
                    "relation_type": "spin_off",
                    "is_from_series_line": True,
                    "is_from_root_node": True,
                },
            ],
        )

    def test_candidate_assembler_keeps_non_series_anchor_information(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [AnimeRelation("999", "300", "other")]

        candidates = UiCandidateAssembler().build(snapshot)
        candidate = candidates[0]

        self.assertIsNone(candidate.linked_series_line_media_id)
        self.assertIsNone(candidate.linked_root_media_id)
        self.assertTrue(candidate.has_non_series_origin)
        self.assertEqual(candidate.source_media_ids, ["999"])
        self.assertEqual(
            candidate.metadata["origins"],
            [
                {
                    "source_media_id": "999",
                    "relation_type": "other",
                    "is_from_series_line": False,
                    "is_from_root_node": False,
                }
            ],
        )

    def test_candidate_assembler_resolves_simple_relation_source_to_series_anchor(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [AnimeRelation("100", "300", "sequel")]

        candidate = UiCandidateAssembler().build(snapshot)[0]

        self.assertEqual(candidate.relation_type, "sequel")
        self.assertEqual(candidate.linked_series_line_media_id, "100")
        self.assertEqual(candidate.relation_source_media_id, "100")

    def test_candidate_assembler_keeps_transitive_relation_source_separate(
        self,
    ):
        tv = AnimeNode("100", "TV", "mal", "tv", "img-100", date(2020, 1, 1), [])
        movie_1 = AnimeNode(
            "201", "Movie 1", "mal", "movie", "img-201", date(2021, 1, 1), []
        )
        movie_2 = AnimeNode(
            "202", "Movie 2", "mal", "movie", "img-202", date(2022, 1, 1), []
        )
        movie_3 = AnimeNode(
            "203", "Movie 3", "mal", "movie", "img-203", date(2023, 1, 1), []
        )
        promoted = [
            AnimeRelation("100", "201", "sequel"),
            AnimeRelation("201", "202", "sequel"),
            AnimeRelation("202", "203", "sequel"),
        ]
        snapshot = SimpleNamespace(
            root_node=tv,
            nodes_by_media_id={
                "100": tv,
                "201": movie_1,
                "202": movie_2,
                "203": movie_3,
            },
            series_line=[tv],
            direct_candidates=[],
            promoted_continuity_candidates=promoted,
            has_series_line=True,
            fallback_anchor_media_id="100",
        )

        candidates = {
            candidate.media_id: candidate
            for candidate in UiCandidateAssembler().build(snapshot)
        }

        self.assertEqual(candidates["201"].linked_series_line_media_id, "100")
        self.assertEqual(candidates["202"].linked_series_line_media_id, "100")
        self.assertEqual(candidates["203"].linked_series_line_media_id, "100")
        self.assertEqual(candidates["201"].relation_type, "sequel")
        self.assertEqual(candidates["202"].relation_type, "sequel")
        self.assertEqual(candidates["203"].relation_type, "sequel")
        self.assertEqual(candidates["201"].relation_source_media_id, "100")
        self.assertEqual(candidates["202"].relation_source_media_id, "201")
        self.assertEqual(candidates["203"].relation_source_media_id, "202")

    def test_candidate_assembler_keeps_badge_and_source_from_same_relation(self):
        snapshot = self._snapshot()
        movie_2 = AnimeNode(
            "301", "Movie 2", "mal", "movie", "img-301", date(2023, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "301": movie_2}
        snapshot.direct_candidates = [
            AnimeRelation("100", "300", "sequel"),
            AnimeRelation("301", "300", "prequel"),
        ]

        candidate = UiCandidateAssembler().build(snapshot)[0]

        self.assertEqual(candidate.media_id, "300")
        self.assertEqual(candidate.relation_type, "sequel")
        self.assertEqual(candidate.relation_source_media_id, "100")
        self.assertEqual(candidate.linked_series_line_media_id, "100")

    def _no_series_line_snapshot(self):
        nodes = [
            AnimeNode(media_id, title, "mal", "special", f"img-{media_id}", start, [])
            for media_id, title, start in [
                ("33142", "Break Time", date(2016, 4, 8)),
                ("33569", "Re:Petit", date(2016, 6, 24)),
                ("42364", "Break Time 2", date(2020, 7, 10)),
                ("60012", "Break Time 3", date(2024, 10, 2)),
                ("63830", "Break Time 4", date(2025, 7, 1)),
            ]
        ]
        nodes_by_media_id = {node.media_id: node for node in nodes}
        return SimpleNamespace(
            root_node=nodes_by_media_id["33569"],
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=[
                AnimeRelation("33142", "33569", "sequel"),
                AnimeRelation("33569", "42364", "sequel"),
                AnimeRelation("42364", "60012", "sequel"),
                AnimeRelation("60012", "63830", "sequel"),
            ],
            continuity_component=nodes,
            series_line=[],
            direct_anchors=[nodes_by_media_id["33569"]],
            direct_candidates=[
                AnimeRelation("33569", "33142", "prequel"),
                AnimeRelation("33569", "42364", "sequel"),
            ],
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            has_series_line=False,
            fallback_anchor_media_id="33569",
            canonical_root_media_id="33142",
        )

    def test_no_series_line_pipeline_exposes_full_continuity_component(self):
        payload = AnimeFranchiseUiPipeline().run(self._no_series_line_snapshot())
        sections = {section["key"]: section for section in payload.sections}

        main_story_extras = sections["continuity_extras"]["entries"]
        self.assertCountEqual(
            [entry["media_id"] for entry in main_story_extras],
            ["33142", "33569", "42364", "60012", "63830"],
        )

    def test_no_series_line_pipeline_orders_continuity_extras_canonically(self):
        snapshot = self._no_series_line_snapshot()
        snapshot.all_normalized_relations = [
            AnimeRelation("33569", "42364", "sequel"),
            AnimeRelation("60012", "63830", "sequel"),
            AnimeRelation("33142", "33569", "sequel"),
            AnimeRelation("42364", "60012", "sequel"),
        ]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertEqual(
            [entry["media_id"] for entry in sections["continuity_extras"]["entries"]],
            ["33142", "33569", "42364", "60012", "63830"],
        )

    def test_series_line_pipeline_ignores_no_series_line_order_metadata(self):
        snapshot = self._snapshot()
        deep_extra = AnimeNode(
            "777", "Deep Extra", "mal", "special", "img-777", date(2024, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "777": deep_extra}
        snapshot.continuity_component = [*snapshot.continuity_component, deep_extra]
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("300", "777", "sequel"),
        ]

        candidates = UiCandidateAssembler().build(snapshot)

        self.assertNotIn("777", {candidate.media_id for candidate in candidates})
        self.assertTrue(
            all(
                "section_sort_rank" not in candidate.metadata
                for candidate in candidates
            )
        )

    def test_no_series_line_pipeline_consumes_snapshot_secondary_candidates(self):
        snapshot = self._no_series_line_snapshot()
        parent = AnimeNode(
            "99999", "Re:Zero S4", "mal", "tv", "img-99999", date(2026, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "99999": parent}
        snapshot.no_series_line_secondary_candidates = [
            AnimeRelation("63830", "99999", "parent_story"),
        ]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertIn(
            "99999",
            [entry["media_id"] for entry in sections["related_series"]["entries"]],
        )
        self.assertNotIn(
            "99999",
            [entry["media_id"] for entry in sections["continuity_extras"]["entries"]],
        )

    def test_no_series_line_pipeline_does_not_derive_secondary_candidates(self):
        snapshot = self._no_series_line_snapshot()
        parent = AnimeNode(
            "99999", "Re:Zero S4", "mal", "tv", "img-99999", date(2026, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "99999": parent}
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("63830", "99999", "parent_story"),
        ]
        snapshot.no_series_line_secondary_candidates = []

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        section_ids = {
            entry["media_id"]
            for section in payload.sections
            for entry in section["entries"]
        }

        self.assertNotIn("99999", section_ids)

    def test_no_series_line_pipeline_does_not_absorb_other_secondary(self):
        snapshot = self._no_series_line_snapshot()
        other = AnimeNode(
            "88888", "Other", "mal", "special", "img-88888", date(2026, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "88888": other}
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("63830", "88888", "other"),
        ]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        section_ids = {
            entry["media_id"]
            for section in payload.sections
            for entry in section["entries"]
        }

        self.assertNotIn("88888", section_ids)

    def test_series_line_pipeline_ignores_deep_parent_story_secondary(self):
        snapshot = self._snapshot()
        parent = AnimeNode(
            "99999", "Deep Parent", "mal", "tv", "img-99999", date(2026, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "99999": parent}
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("300", "99999", "parent_story"),
        ]

        candidates = UiCandidateAssembler().build(snapshot)

        self.assertNotIn("99999", {candidate.media_id for candidate in candidates})

    def test_no_series_line_pipeline_does_not_absorb_related_relations(self):
        snapshot = self._no_series_line_snapshot()
        extra_nodes = {
            "100": AnimeNode("100", "Main Series", "mal", "tv", "img-100", None, []),
            "200": AnimeNode("200", "Parent", "mal", "tv", "img-200", None, []),
            "300": AnimeNode("300", "Random", "mal", "special", "img-300", None, []),
        }
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, **extra_nodes}
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("33569", "100", "side_story"),
            AnimeRelation("33569", "200", "parent_story"),
            AnimeRelation("33569", "300", "spin_off"),
        ]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}
        main_story_ids = [
            entry["media_id"] for entry in sections["continuity_extras"]["entries"]
        ]

        self.assertCountEqual(
            main_story_ids,
            ["33142", "33569", "42364", "60012", "63830"],
        )
        self.assertNotIn("100", main_story_ids)
        self.assertNotIn("200", main_story_ids)
        self.assertNotIn("300", main_story_ids)

    def test_series_line_pipeline_does_not_consume_all_normalized_relations(self):
        snapshot = self._snapshot()
        deep_extra = AnimeNode(
            "777", "Deep Extra", "mal", "special", "img-777", date(2024, 1, 1), []
        )
        snapshot.nodes_by_media_id = {**snapshot.nodes_by_media_id, "777": deep_extra}
        snapshot.all_normalized_relations = [
            *snapshot.all_normalized_relations,
            AnimeRelation("300", "777", "sequel"),
        ]

        candidates = UiCandidateAssembler().build(snapshot)

        self.assertNotIn("777", {candidate.media_id for candidate in candidates})

    def test_no_series_line_transitive_candidates_keep_relation_source(self):
        snapshot = self._no_series_line_snapshot()
        candidates = {
            candidate.media_id: candidate
            for candidate in UiCandidateAssembler().build(snapshot)
        }

        self.assertEqual(candidates["60012"].relation_source_media_id, "42364")
        self.assertEqual(candidates["63830"].relation_source_media_id, "60012")
        self.assertEqual(candidates["60012"].relation_type, "sequel")
        self.assertEqual(candidates["63830"].relation_types, ["sequel"])
        self.assertEqual(candidates["60012"].source_media_ids, ["42364"])
        self.assertEqual(
            candidates["63830"].metadata["origins"],
            [
                {
                    "source_media_id": "60012",
                    "relation_type": "sequel",
                    "is_from_series_line": False,
                    "is_from_root_node": False,
                }
            ],
        )

    def test_root_story_parent_goes_to_related_series(self):
        root = AnimeNode(
            "27891", "Debriefing", "mal", "special", "img-27891", date(2014, 1, 1), []
        )
        parent = AnimeNode(
            "100", "SAO II", "mal", "tv", "img-100", date(2014, 7, 1), []
        )
        snapshot = SimpleNamespace(
            root_node=root,
            nodes_by_media_id={"27891": root, "100": parent},
            all_normalized_relations=[AnimeRelation("27891", "100", "full_story")],
            continuity_component=[root],
            series_line=[],
            direct_anchors=[root],
            direct_candidates=[],
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            root_story_parent_candidates=[AnimeRelation("27891", "100", "full_story")],
            has_series_line=False,
            fallback_anchor_media_id="27891",
            canonical_root_media_id="27891",
        )

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertIn(
            "100",
            [entry["media_id"] for entry in sections["related_series"]["entries"]],
        )
        self.assertNotIn(
            "100",
            [
                entry["media_id"]
                for entry in sections.get("specials", {"entries": []})["entries"]
            ],
        )
        self.assertNotIn(
            "100",
            [
                entry["media_id"]
                for entry in sections.get("ignored", {"entries": []})["entries"]
            ],
        )

    def test_full_story_without_root_story_parent_metadata_stays_special(self):
        root = AnimeNode(
            "27891", "Debriefing", "mal", "special", "img-27891", date(2014, 1, 1), []
        )
        parent = AnimeNode(
            "100", "SAO II", "mal", "special", "img-100", date(2014, 7, 1), []
        )
        snapshot = SimpleNamespace(
            root_node=root,
            nodes_by_media_id={"27891": root, "100": parent},
            all_normalized_relations=[AnimeRelation("27891", "100", "full_story")],
            continuity_component=[root],
            series_line=[],
            direct_anchors=[root],
            direct_candidates=[AnimeRelation("27891", "100", "full_story")],
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            root_story_parent_candidates=[],
            has_series_line=False,
            fallback_anchor_media_id="27891",
            canonical_root_media_id="27891",
        )

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertIn(
            "100", [entry["media_id"] for entry in sections["specials"]["entries"]]
        )
        self.assertNotIn(
            "100",
            [
                entry["media_id"]
                for entry in sections.get("related_series", {"entries": []})["entries"]
            ],
        )

    def test_inverse_tv_to_recap_full_story_stays_specials(self):
        tv = AnimeNode("100", "SAO II", "mal", "tv", "img-100", date(2014, 7, 1), [])
        recap = AnimeNode(
            "27891", "Debriefing", "mal", "special", "img-27891", date(2014, 1, 1), []
        )
        snapshot = SimpleNamespace(
            root_node=tv,
            nodes_by_media_id={"100": tv, "27891": recap},
            all_normalized_relations=[AnimeRelation("100", "27891", "full_story")],
            continuity_component=[tv, recap],
            series_line=[tv],
            direct_anchors=[tv],
            direct_candidates=[AnimeRelation("100", "27891", "full_story")],
            promoted_continuity_candidates=[],
            no_series_line_secondary_candidates=[],
            root_story_parent_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="100",
            canonical_root_media_id="100",
        )

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertIn(
            "27891", [entry["media_id"] for entry in sections["specials"]["entries"]]
        )
        self.assertNotIn(
            "27891",
            [
                entry["media_id"]
                for entry in sections.get("related_series", {"entries": []})["entries"]
            ],
        )

    def test_pipeline_output_contains_root_display_and_expected_sections(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())

        self.assertEqual(payload.root_media_id, "200")
        self.assertEqual(payload.display_title, "Season 2")
        self.assertEqual(payload.series["key"], "series")
        self.assertEqual(payload.series["title"], "Series")
        section_keys = [section["key"] for section in payload.sections]
        self.assertIn("specials", section_keys)
        specials = next(
            section for section in payload.sections if section["key"] == "specials"
        )
        self.assertEqual(specials["title"], "Specials")
        self.assertIn("media_type", payload.series["entries"][0])
        self.assertIn("anime_media_type", payload.series["entries"][0])

    def test_pipeline_prefers_relation_types_for_ambiguous_candidates(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation("200", "300", "other"),
            AnimeRelation("200", "300", "side_story"),
        ]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertEqual(
            [entry["media_id"] for entry in sections["specials"]["entries"]],
            ["300"],
        )
        self.assertNotIn("ignored", sections)

    def test_adapter_output_keeps_footer_and_enrichment_fields(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())
        entry = payload.sections[0]["entries"][0]

        self.assertEqual(entry["media_type"], "anime")
        self.assertIn("anime_media_type", entry)
        self.assertIn("relation_type", entry)
        self.assertIn("linked_series_line_media_id", entry)
        self.assertIn("linked_series_line_index", entry)
        self.assertIn("relation_source_media_id", entry)
        self.assertIn("is_current", entry)

    def test_ignored_section_is_not_visible_in_ui(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())
        ignored = next(
            section for section in payload.sections if section["key"] == "ignored"
        )
        self.assertFalse(ignored["visible_in_ui"])

    def test_predicates_runtime_episode_and_relation_comparators(self):
        candidate = UiCandidate(
            media_id="300",
            title="Movie",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="side_story",
            start_date=date(2022, 1, 1),
            runtime_minutes=95,
            episode_count=1,
            linked_series_line_media_id="200",
            linked_series_line_index=1,
        )
        context = RuleContext(snapshot=self._snapshot())

        self.assertTrue(relation_type_is("side_story")(candidate, context))
        self.assertTrue(runtime_minutes_lt(100)(candidate, context))
        self.assertTrue(runtime_minutes_lte(95)(candidate, context))
        self.assertTrue(runtime_minutes_gt(90)(candidate, context))
        self.assertTrue(runtime_minutes_gte(95)(candidate, context))
        self.assertTrue(runtime_minutes_eq(95)(candidate, context))
        self.assertTrue(episode_count_lt(2)(candidate, context))
        self.assertTrue(episode_count_lte(1)(candidate, context))
        self.assertFalse(episode_count_gt(1)(candidate, context))
        self.assertTrue(episode_count_gte(1)(candidate, context))
        self.assertTrue(episode_count_eq(1)(candidate, context))

    def test_layout_compiler_groups_orders_and_hides_empty_sections(self):
        context = RuleContext(
            snapshot=self._snapshot(),
            sections={
                "early_section": SectionDefinition(
                    key="early_section",
                    title="Early Section",
                    order=50,
                    hidden_if_empty=True,
                ),
                "late_section": SectionDefinition(
                    key="late_section",
                    title="Late Section",
                    order=200,
                    hidden_if_empty=True,
                ),
                "empty_hidden": SectionDefinition(
                    key="empty_hidden",
                    title="Empty Hidden",
                    order=10,
                    hidden_if_empty=True,
                ),
            },
        )
        candidates = [
            UiCandidate(
                media_id="301",
                title="Entry A",
                image="img-a",
                source="mal",
                media_type="movie",
                relation_type="other",
                start_date=None,
                runtime_minutes=None,
                episode_count=None,
                linked_series_line_media_id=None,
                linked_series_line_index=None,
                section_key="late_section",
            ),
            UiCandidate(
                media_id="302",
                title="Entry B",
                image="img-b",
                source="mal",
                media_type="ova",
                relation_type="other",
                start_date=None,
                runtime_minutes=None,
                episode_count=None,
                linked_series_line_media_id=None,
                linked_series_line_index=None,
                section_key="early_section",
            ),
        ]

        sections = LayoutCompiler().compile(candidates=candidates, context=context)

        self.assertEqual(
            [section.key for section in sections], ["early_section", "late_section"]
        )
        self.assertEqual([entry.media_id for entry in sections[0].entries], ["302"])
        self.assertEqual([entry.media_id for entry in sections[1].entries], ["301"])
        self.assertNotIn("empty_hidden", [section.key for section in sections])

    def test_layout_compiler_uses_explicit_fallback_definition_for_undefined_key(self):
        context = RuleContext(snapshot=self._snapshot())
        candidates = [
            UiCandidate(
                media_id="777",
                title="Undefined Section Entry",
                image="img",
                source="mal",
                media_type="movie",
                relation_type="other",
                start_date=None,
                runtime_minutes=None,
                episode_count=None,
                linked_series_line_media_id=None,
                linked_series_line_index=None,
                section_key="undefined_bucket",
            )
        ]

        sections = LayoutCompiler().compile(candidates=candidates, context=context)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].key, "undefined_bucket")
        self.assertEqual(sections[0].title, "Undefined Bucket")

    def test_layout_compiler_propagates_section_metadata(self):
        context = RuleContext(
            snapshot=self._snapshot(),
            sections={
                "meta_section": SectionDefinition(
                    key="meta_section",
                    title="Meta",
                    order=1,
                    hidden_if_empty=False,
                    metadata={"visible_in_ui": False, "kind": "internal"},
                )
            },
        )
        candidate = UiCandidate(
            media_id="901",
            title="Meta Entry",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id=None,
            linked_series_line_index=None,
            section_key="meta_section",
        )

        sections = LayoutCompiler().compile(candidates=[candidate], context=context)

        self.assertEqual(sections[0].metadata["visible_in_ui"], False)
        self.assertEqual(sections[0].metadata["kind"], "internal")

    def test_adapter_reads_visible_in_ui_from_section_metadata(self):
        payload = ViewModelAdapter().adapt(
            root_media_id="1",
            canonical_root_media_id="1",
            display_title="Root",
            series_block=SeriesBuilder().build(self._snapshot()),
            sections=[
                CompiledSection(
                    key="ignored",
                    title="Ignored",
                    order=10,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                    entries=[],
                )
            ],
        )

        self.assertTrue(payload.sections[0]["visible_in_ui"])

    def test_section_definition_can_be_refined_after_initial_ensure(self):
        context = RuleContext(snapshot=self._snapshot())
        candidate = UiCandidate(
            media_id="888",
            title="Section Refinement Target",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id=None,
            linked_series_line_index=None,
        )

        ensure_section(
            key="refine_me",
            title="Initial Title",
            order=300,
            hidden_if_empty=True,
        )(candidate, context)
        set_section_title(key="refine_me", title="Refined Title")(candidate, context)
        set_section_order(key="refine_me", order=50)(candidate, context)
        set_section_hidden_if_empty(key="refine_me", hidden_if_empty=False)(
            candidate, context
        )

        definition = context.sections["refine_me"]
        self.assertEqual(definition.title, "Refined Title")
        self.assertEqual(definition.order, 50)
        self.assertFalse(definition.hidden_if_empty)

    def test_ensure_section_is_create_only_and_does_not_overwrite(self):
        context = RuleContext(snapshot=self._snapshot())
        candidate = UiCandidate(
            media_id="999",
            title="No Overwrite",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id=None,
            linked_series_line_index=None,
        )

        ensure_section(
            key="create_once",
            title="First",
            order=10,
            hidden_if_empty=True,
        )(candidate, context)
        ensure_section(
            key="create_once",
            title="Second",
            order=999,
            hidden_if_empty=False,
        )(candidate, context)

        definition = context.sections["create_once"]
        self.assertEqual(definition.title, "First")
        self.assertEqual(definition.order, 10)
        self.assertTrue(definition.hidden_if_empty)

    def test_run_once_predicate_runs_once_per_state_key(self):
        context = RuleContext(snapshot=self._snapshot())
        candidate = UiCandidate(
            media_id="910",
            title="Set State",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id=None,
            linked_series_line_index=None,
        )

        predicate = run_once("my_once")

        self.assertTrue(predicate(candidate, context))
        self.assertFalse(predicate(candidate, context))

    def test_rule_pipeline_rule_can_read_snapshot_from_context(self):
        snapshot = self._snapshot()
        context = RuleContext(snapshot=snapshot)
        candidate = UiCandidate(
            media_id="500",
            title="Rule Target",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id=None,
            linked_series_line_index=None,
        )

        def when_snapshot_root_matches(current_candidate, current_context):
            return (
                current_context.snapshot.root_node.media_id == "200"
                and current_candidate.media_id == "500"
            )

        def place_in_snapshot_section(current_candidate, _current_context):
            current_candidate.section_key = "snapshot_driven"

        pipeline = RulePipeline(
            packs=[
                RulePack(
                    key="test_pack",
                    rules=(
                        Rule(
                            key="snapshot_access_rule",
                            when=when_snapshot_root_matches,
                            actions=(place_in_snapshot_section,),
                        ),
                    ),
                )
            ]
        )

        pipeline.run(candidates=[candidate], context=context)

        self.assertEqual(candidate.section_key, "snapshot_driven")

    def test_rule_pipeline_tracks_section_key_overrides(self):
        context = RuleContext(snapshot=self._snapshot())
        candidate = UiCandidate(
            media_id="501",
            title="Trace Target",
            image="img",
            source="mal",
            media_type="movie",
            relation_type="other",
            relation_types=["other", "side_story"],
            start_date=None,
            runtime_minutes=None,
            episode_count=None,
            linked_series_line_media_id="200",
            linked_series_line_index=1,
            metadata={"origins": []},
        )

        pipeline = RulePipeline(
            packs=[
                RulePack(
                    key="pack_one",
                    rules=(
                        Rule(
                            key="initial_rule",
                            when=lambda *_args: True,
                            actions=(
                                lambda current_candidate, _ctx: setattr(
                                    current_candidate, "section_key", "related_series"
                                ),
                            ),
                        ),
                    ),
                ),
                RulePack(
                    key="pack_two",
                    rules=(
                        Rule(
                            key="override_rule",
                            when=lambda *_args: True,
                            actions=(
                                lambda current_candidate, _ctx: setattr(
                                    current_candidate, "section_key", "specials"
                                ),
                            ),
                        ),
                    ),
                ),
            ]
        )

        pipeline.run(candidates=[candidate], context=context)

        self.assertEqual(candidate.section_key, "specials")
        self.assertEqual(
            candidate.metadata["placement_trace"],
            [
                {
                    "pack": "pack_one",
                    "rule": "initial_rule",
                    "from": None,
                    "to": "related_series",
                    "kind": "initial",
                },
                {
                    "pack": "pack_two",
                    "rule": "override_rule",
                    "from": "related_series",
                    "to": "specials",
                    "kind": "override",
                },
            ],
        )

    def test_internal_placement_trace_is_not_exposed_by_adapter_payload(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())
        all_entries = payload.series["entries"] + [
            entry for section in payload.sections for entry in section["entries"]
        ]
        for entry in all_entries:
            self.assertNotIn("placement_trace", entry)
