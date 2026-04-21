from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline
from app.services.anime_franchise_ui.actions import ensure_section, set_section_order, set_section_title
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
    runtime_minutes_eq,
    runtime_minutes_gt,
    runtime_minutes_gte,
    runtime_minutes_lt,
    runtime_minutes_lte,
)
from app.services.anime_franchise_ui.rule_types import (
    Rule,
    RuleContext,
    RulePack,
    SectionDefinition,
)
from app.services.anime_franchise_ui.series import SeriesBuilder


class AnimeFranchiseUiPipelineTests(TestCase):
    def _snapshot(self):
        series_1 = AnimeNode("100", "Season 1", "mal", "tv", "img-100", date(2020, 1, 1), [])
        series_2 = AnimeNode("200", "Season 2", "mal", "tv", "img-200", date(2021, 1, 1), [])
        movie = AnimeNode("300", "Movie", "mal", "movie", "img-300", date(2022, 1, 1), [])
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
            has_series_line=True,
            fallback_anchor_media_id="200",
            canonical_root_media_id="100",
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

        self.assertEqual({candidate.media_id for candidate in candidates}, {"300", "400"})
        self.assertEqual(len(candidates), 2)

    def test_candidate_assembler_preserves_multi_origin_signals_for_same_media(self):
        snapshot = self._snapshot()
        candidates = UiCandidateAssembler().build(snapshot)
        movie_candidate = next(candidate for candidate in candidates if candidate.media_id == "300")

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

    def test_pipeline_output_contains_root_display_and_neutral_fallback(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())

        self.assertEqual(payload.root_media_id, "200")
        self.assertEqual(payload.display_title, "Season 2")
        self.assertEqual(payload.series["key"], "series")
        self.assertEqual(payload.series["title"], "Series")
        self.assertEqual(payload.sections[0]["key"], "other_entries")
        self.assertEqual(payload.sections[0]["title"], "Other Entries")

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

        self.assertEqual([section.key for section in sections], ["early_section", "late_section"])
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

        definition = context.sections["refine_me"]
        self.assertEqual(definition.title, "Refined Title")
        self.assertEqual(definition.order, 50)

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
