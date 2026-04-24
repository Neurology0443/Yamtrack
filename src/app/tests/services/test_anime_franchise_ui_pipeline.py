from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from app.models import Sources
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
    runtime_minutes_eq,
    runtime_minutes_gt,
    runtime_minutes_gte,
    runtime_minutes_lt,
    runtime_minutes_lte,
    run_once,
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
            promoted_continuity_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="200",
            canonical_root_media_id="100",
        )

    class _FakeClassificationGraphBuilder:
        def __init__(self, nodes_by_media_id: dict[str, AnimeNode] | None = None):
            self.nodes_by_media_id = nodes_by_media_id or {}
            self.ensure_classification_node_calls: list[str] = []
            self.ensure_node_calls: list[str] = []

        def ensure_classification_node(self, media_id: str) -> AnimeNode:
            media_id = str(media_id)
            self.ensure_classification_node_calls.append(media_id)
            return self.nodes_by_media_id[media_id]

        def ensure_node(self, media_id: str):  # pragma: no cover - guard only
            self.ensure_node_calls.append(str(media_id))
            raise AssertionError("ensure_node() must not be called for classification enrichment")

    def _pipeline(self, classification_nodes: dict[str, AnimeNode] | None = None):
        graph_builder = self._FakeClassificationGraphBuilder(classification_nodes)
        return AnimeFranchiseUiPipeline(classification_graph_builder=graph_builder), graph_builder

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

    def test_candidate_assembler_emits_light_candidate_when_target_node_is_missing(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation("200", "901", "spin_off"),
            AnimeRelation(
                "201",
                "901",
                "side_story",
                target_title="Satellite 901",
                target_image="img-901",
                target_source=Sources.MAL.value,
            ),
        ]
        snapshot.nodes_by_media_id.pop("901", None)

        candidates = UiCandidateAssembler().build(snapshot)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]

        self.assertEqual(candidate.media_id, "901")
        self.assertEqual(candidate.title, "Satellite 901")
        self.assertEqual(candidate.image, "img-901")
        self.assertEqual(candidate.source, Sources.MAL.value)
        self.assertEqual(candidate.media_type, "")
        self.assertTrue(candidate.is_light)
        self.assertEqual(candidate.route_media_type, "anime")
        self.assertIsNone(candidate.start_date)
        self.assertIsNone(candidate.runtime_minutes)
        self.assertIsNone(candidate.episode_count)
        self.assertEqual(candidate.relation_type, "spin_off")
        self.assertEqual(candidate.relation_types, ["spin_off", "side_story"])
        self.assertEqual(candidate.source_media_ids, ["200", "201"])
        self.assertEqual(candidate.linked_series_line_media_id, "200")
        self.assertEqual(candidate.metadata["is_light"], True)
        self.assertEqual(candidate.metadata["route_media_type"], "anime")

    def test_pipeline_output_contains_root_display_and_expected_sections(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())

        self.assertEqual(payload.root_media_id, "200")
        self.assertEqual(payload.display_title, "Season 2")
        self.assertEqual(payload.series["key"], "series")
        self.assertEqual(payload.series["title"], "Series")
        section_keys = [section["key"] for section in payload.sections]
        self.assertIn("specials", section_keys)
        specials = next(section for section in payload.sections if section["key"] == "specials")
        self.assertEqual(specials["title"], "Specials")
        self.assertIn("media_type", payload.series["entries"][0])
        self.assertIn("anime_media_type", payload.series["entries"][0])

    def test_pipeline_prefers_relation_types_for_ambiguous_candidates(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [AnimeRelation("200", "300", "other"), AnimeRelation("200", "300", "side_story")]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertEqual(
            [entry["media_id"] for entry in sections["specials"]["entries"]],
            ["300"],
        )
        self.assertNotIn("ignored", sections)

    def test_unknown_media_type_in_specials_is_not_ignored(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation(
                "200",
                "902",
                "side_story",
                target_title="Unknown Format Special",
                target_image="img-902",
                target_source=Sources.MAL.value,
            )
        ]
        snapshot.nodes_by_media_id.pop("902", None)
        pipeline, graph_builder = self._pipeline(
            {
                "902": AnimeNode(
                    "902",
                    "Unknown Format Special",
                    Sources.MAL.value,
                    "",
                    "img-902",
                    date(2022, 8, 1),
                    [],
                    runtime_minutes=24,
                )
            }
        )
        payload = pipeline.run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertIn("specials", sections)
        self.assertEqual(
            [entry["media_id"] for entry in sections["specials"]["entries"]],
            ["902"],
        )
        self.assertEqual(graph_builder.ensure_classification_node_calls, ["902"])

    def test_light_spin_off_candidate_is_classification_enriched_and_promoted_to_spin_offs(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation(
                "200",
                "51958",
                "spin_off",
                target_title="Spin Off 51958",
                target_image="img-51958",
                target_source=Sources.MAL.value,
            )
        ]
        snapshot.nodes_by_media_id.pop("51958", None)
        pipeline, graph_builder = self._pipeline(
            {
                "51958": AnimeNode(
                    "51958",
                    "Spin Off 51958",
                    Sources.MAL.value,
                    "tv",
                    "img-51958",
                    date(2023, 5, 1),
                    [],
                    runtime_minutes=24,
                    episode_count=None,
                )
            }
        )
        payload = pipeline.run(snapshot)
        spin_offs = next(section for section in payload.sections if section["key"] == "spin_offs")
        entry = next(entry for entry in spin_offs["entries"] if entry["media_id"] == "51958")

        self.assertEqual(graph_builder.ensure_classification_node_calls, ["51958"])
        self.assertEqual(graph_builder.ensure_node_calls, [])
        self.assertEqual(entry["media_type"], "anime")
        self.assertEqual(entry["anime_media_type"], "tv")
        self.assertEqual(entry["runtime_minutes"], 24)
        self.assertTrue(entry["is_light"])
        self.assertIsNone(entry["episode_count"])

    def test_candidate_assembler_non_light_candidate_has_known_format(self):
        snapshot = self._snapshot()
        candidates = UiCandidateAssembler().build(snapshot)
        movie_candidate = next(candidate for candidate in candidates if candidate.media_id == "300")

        self.assertFalse(movie_candidate.is_light)
        self.assertEqual(movie_candidate.route_media_type, "anime")
        self.assertEqual(movie_candidate.media_type, "movie")

    def test_specials_known_tv_format_is_ignored(self):
        snapshot = self._snapshot()
        snapshot.nodes_by_media_id["905"] = AnimeNode(
            "905",
            "TV Special Candidate",
            Sources.MAL.value,
            "tv",
            "img-905",
            date(2022, 7, 1),
            [],
        )
        snapshot.direct_candidates = [AnimeRelation("200", "905", "side_story")]

        payload = AnimeFranchiseUiPipeline().run(snapshot)
        sections = {section["key"]: section for section in payload.sections}

        self.assertNotIn(
            "905",
            [entry["media_id"] for entry in sections["specials"]["entries"]],
        )
        self.assertIn(
            "905",
            [entry["media_id"] for entry in sections["ignored"]["entries"]],
        )

    def test_light_alternative_candidate_is_not_classification_enriched(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation(
                "200",
                "990",
                "alternative_version",
                target_title="Alternative 990",
                target_image="img-990",
                target_source=Sources.MAL.value,
            )
        ]
        snapshot.nodes_by_media_id.pop("990", None)
        pipeline, graph_builder = self._pipeline(
            {
                "990": AnimeNode(
                    "990",
                    "Alternative 990",
                    Sources.MAL.value,
                    "tv",
                    "img-990",
                    date(2025, 1, 1),
                    [],
                    runtime_minutes=24,
                )
            }
        )

        payload = pipeline.run(snapshot)
        alternatives = next(section for section in payload.sections if section["key"] == "alternatives")
        entry = alternatives["entries"][0]

        self.assertEqual(entry["media_id"], "990")
        self.assertEqual(entry["anime_media_type"], "")
        self.assertTrue(entry["is_light"])
        self.assertEqual(graph_builder.ensure_classification_node_calls, [])
        self.assertEqual(graph_builder.ensure_node_calls, [])

    def test_light_side_story_with_known_tv_format_is_filtered_from_specials(self):
        snapshot = self._snapshot()
        snapshot.direct_candidates = [
            AnimeRelation(
                "200",
                "991",
                "side_story",
                target_title="Side Story 991",
                target_image="img-991",
                target_source=Sources.MAL.value,
            )
        ]
        snapshot.nodes_by_media_id.pop("991", None)
        pipeline, _graph_builder = self._pipeline(
            {
                "991": AnimeNode(
                    "991",
                    "Side Story 991",
                    Sources.MAL.value,
                    "tv",
                    "img-991",
                    date(2024, 2, 1),
                    [],
                    runtime_minutes=24,
                )
            }
        )

        payload = pipeline.run(snapshot)
        sections = {section["key"]: section for section in payload.sections}
        self.assertNotIn("991", [entry["media_id"] for entry in sections["specials"]["entries"]])
        self.assertIn("991", [entry["media_id"] for entry in sections["related_series"]["entries"]])

    def test_demon_slayer_movie_chain_light_candidates_remain_visible(self):
        season_1 = AnimeNode("100", "Season 1", Sources.MAL.value, "tv", "img-100", date(2020, 1, 1), [])
        season_2 = AnimeNode("101", "Season 2", Sources.MAL.value, "tv", "img-101", date(2021, 1, 1), [])
        snapshot = SimpleNamespace(
            root_node=season_2,
            nodes_by_media_id={"100": season_1, "101": season_2},
            all_normalized_relations=[],
            continuity_component=[season_1, season_2],
            series_line=[season_1, season_2],
            direct_anchors=[season_1, season_2],
            direct_candidates=[
                AnimeRelation(
                    "101",
                    "200",
                    "sequel",
                    target_title="Movie 1",
                    target_image="img-200",
                    target_source=Sources.MAL.value,
                ),
            ],
            promoted_continuity_candidates=[
                AnimeRelation(
                    "200",
                    "201",
                    "sequel",
                    target_title="Movie 2",
                    target_image="img-201",
                    target_source=Sources.MAL.value,
                ),
                AnimeRelation(
                    "201",
                    "202",
                    "sequel",
                    target_title="Movie 3",
                    target_image="img-202",
                    target_source=Sources.MAL.value,
                ),
            ],
            has_series_line=True,
            fallback_anchor_media_id="101",
            canonical_root_media_id="100",
        )

        pipeline, _graph_builder = self._pipeline(
            {
                "200": AnimeNode("200", "Movie 1", Sources.MAL.value, "movie", "img-200", date(2022, 1, 1), [], runtime_minutes=117),
                "201": AnimeNode("201", "Movie 2", Sources.MAL.value, "movie", "img-201", date(2023, 1, 1), [], runtime_minutes=122),
                "202": AnimeNode("202", "Movie 3", Sources.MAL.value, "movie", "img-202", date(2024, 1, 1), [], runtime_minutes=125),
            }
        )
        payload = pipeline.run(snapshot)
        sections = {section["key"]: section for section in payload.sections}
        related_series_ids = [
            entry["media_id"]
            for entry in sections["related_series"]["entries"]
        ]
        self.assertEqual(related_series_ids, ["200", "201", "202"])
        for entry in sections["related_series"]["entries"]:
            self.assertEqual(entry["media_type"], "anime")
            self.assertEqual(entry["anime_media_type"], "movie")
            self.assertTrue(entry["is_light"])

    def test_adapter_output_keeps_footer_and_enrichment_fields(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())
        entry = payload.sections[0]["entries"][0]

        self.assertEqual(entry["media_type"], "anime")
        self.assertIn("anime_media_type", entry)
        self.assertIn("relation_type", entry)
        self.assertIn("linked_series_line_media_id", entry)
        self.assertIn("linked_series_line_index", entry)
        self.assertIn("is_current", entry)

    def test_ignored_section_is_not_visible_in_ui(self):
        payload = AnimeFranchiseUiPipeline().run(self._snapshot())
        ignored = next(section for section in payload.sections if section["key"] == "ignored")
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
        set_section_hidden_if_empty(key="refine_me", hidden_if_empty=False)(candidate, context)

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
                            actions=(lambda current_candidate, _ctx: setattr(current_candidate, "section_key", "related_series"),),
                        ),
                    ),
                ),
                RulePack(
                    key="pack_two",
                    rules=(
                        Rule(
                            key="override_rule",
                            when=lambda *_args: True,
                            actions=(lambda current_candidate, _ctx: setattr(current_candidate, "section_key", "specials"),),
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
