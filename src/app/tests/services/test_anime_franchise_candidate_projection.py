# ruff: noqa: D101,D102,D107
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from app.services.anime_franchise_candidate_projection import build_franchise_candidates
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder
from app.services.anime_franchise_ui_policy_resolver import resolve_ui_policy_suite


class AnimeFranchiseCandidateProjectionTests(SimpleTestCase):
    def _node(self, media_id, title, media_type, start_date, *, runtime_minutes=None, episode_count=None):
        return AnimeNode(
            media_id=str(media_id),
            title=title,
            source="mal",
            media_type=media_type,
            image=f"img-{media_id}",
            start_date=start_date,
            relations=[],
            runtime_minutes=runtime_minutes,
            episode_count=episode_count,
        )

    def _snapshot(
        self,
        *,
        root_node,
        series_line,
        direct_candidates,
        nodes_by_media_id,
        has_series_line,
        fallback_anchor_media_id,
    ):
        return AnimeFranchiseSnapshot(
            root_node=root_node,
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=[],
            continuity_component=list(nodes_by_media_id.values()),
            series_line=series_line,
            direct_anchors=[],
            direct_candidates=direct_candidates,
            has_series_line=has_series_line,
            fallback_anchor_media_id=fallback_anchor_media_id,
            canonical_root_media_id=root_node.media_id,
        )

    def test_builds_expected_candidates_from_snapshot(self):
        s1 = self._node("100", "Series S1", "tv", date(2010, 1, 1))
        s2 = self._node("101", "Series S2", "tv", date(2011, 1, 1))
        movie = self._node("200", "Movie", "movie", date(2012, 1, 1))

        snapshot = self._snapshot(
            root_node=s2,
            series_line=[s1, s2],
            direct_candidates=[AnimeRelation("101", "200", "sequel")],
            nodes_by_media_id={n.media_id: n for n in [s1, s2, movie]},
            has_series_line=True,
            fallback_anchor_media_id="101",
        )

        candidates = build_franchise_candidates(snapshot)

        self.assertEqual(list(candidates), ["200"])
        candidate = candidates["200"]
        self.assertEqual(candidate.title, "Movie")
        self.assertEqual(candidate.linked_series_line_media_id, "101")
        self.assertEqual(candidate.linked_series_line_index, 1)
        self.assertTrue(candidate.is_direct_from_series_line)

    def test_ignores_candidates_already_in_series_line(self):
        s1 = self._node("100", "Series S1", "tv", date(2010, 1, 1))
        s2 = self._node("101", "Series S2", "tv", date(2011, 1, 1))

        snapshot = self._snapshot(
            root_node=s1,
            series_line=[s1, s2],
            direct_candidates=[AnimeRelation("100", "101", "sequel")],
            nodes_by_media_id={n.media_id: n for n in [s1, s2]},
            has_series_line=True,
            fallback_anchor_media_id="100",
        )

        self.assertEqual(build_franchise_candidates(snapshot), {})

    def test_uses_fallback_anchor_without_series_line(self):
        root = self._node("500", "Movie Root", "movie", date(2018, 1, 1))
        spinoff = self._node("501", "Spin Off", "movie", date(2019, 1, 1))

        snapshot = self._snapshot(
            root_node=root,
            series_line=[],
            direct_candidates=[AnimeRelation("999", "501", "spin_off")],
            nodes_by_media_id={n.media_id: n for n in [root, spinoff]},
            has_series_line=False,
            fallback_anchor_media_id="500",
        )

        candidates = build_franchise_candidates(snapshot)
        self.assertEqual(candidates["501"].linked_series_line_media_id, "500")
        self.assertEqual(candidates["501"].linked_series_line_index, 0)

    def test_runtime_and_episode_default_to_none_when_missing(self):
        s1 = self._node("100", "Series S1", "tv", date(2010, 1, 1))
        target = self._node("300", "Runtime Target", "movie", date(2012, 1, 1))

        snapshot = self._snapshot(
            root_node=s1,
            series_line=[s1],
            direct_candidates=[AnimeRelation("100", "300", "sequel")],
            nodes_by_media_id={n.media_id: n for n in [s1, target]},
            has_series_line=True,
            fallback_anchor_media_id="100",
        )

        candidate = build_franchise_candidates(snapshot)["300"]
        self.assertIsNone(candidate.runtime_minutes)
        self.assertIsNone(candidate.episode_count)

    def test_populates_runtime_and_episode_count_when_available(self):
        s1 = self._node("100", "Series S1", "tv", date(2010, 1, 1))
        target = self._node(
            "300",
            "Runtime Target",
            "movie",
            date(2012, 1, 1),
            runtime_minutes=97,
            episode_count=1,
        )

        snapshot = self._snapshot(
            root_node=s1,
            series_line=[s1],
            direct_candidates=[AnimeRelation("100", "300", "sequel")],
            nodes_by_media_id={n.media_id: n for n in [s1, target]},
            has_series_line=True,
            fallback_anchor_media_id="100",
        )

        candidate = build_franchise_candidates(snapshot)["300"]
        self.assertEqual(candidate.runtime_minutes, 97)
        self.assertEqual(candidate.episode_count, 1)

    def test_keeps_best_candidate_per_media_id(self):
        s1 = self._node("100", "Series S1", "tv", date(2010, 1, 1))
        s2 = self._node("101", "Series S2", "tv", date(2011, 1, 1))
        target = self._node("300", "Shared Target", "movie", date(2011, 6, 1))

        snapshot = self._snapshot(
            root_node=s1,
            series_line=[s1, s2],
            direct_candidates=[
                AnimeRelation("101", "300", "sequel"),
                AnimeRelation("100", "300", "prequel"),
            ],
            nodes_by_media_id={n.media_id: n for n in [s1, s2, target]},
            has_series_line=True,
            fallback_anchor_media_id="100",
        )

        candidates = build_franchise_candidates(snapshot)
        self.assertEqual(candidates["300"].linked_series_line_media_id, "100")
        self.assertEqual(candidates["300"].relation_type, "prequel")


class AnimeFranchiseUiBuilderProjectionRegressionTests(SimpleTestCase):
    def test_builder_pipeline_keeps_grouping_order_and_profiles(self):
        nodes = {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
            "205": AnimeNode("205", "Spin Off Special", "mal", "special", "img", date(2011, 5, 1)),
            "206": AnimeNode("206", "Character Story", "mal", "special", "img", date(2011, 6, 1)),
            "207": AnimeNode("207", "Preview short", "mal", "ova", "img", date(2011, 7, 1)),
        }

        snapshot = AnimeFranchiseSnapshot(
            root_node=nodes["101"],
            nodes_by_media_id=nodes,
            all_normalized_relations=[],
            continuity_component=[nodes["100"], nodes["101"]],
            series_line=[nodes["100"], nodes["101"]],
            direct_anchors=[nodes["100"], nodes["101"]],
            direct_candidates=[
                AnimeRelation("100", "204", "spin_off"),
                AnimeRelation("100", "205", "spin_off"),
                AnimeRelation("100", "206", "character"),
                AnimeRelation("100", "207", "side_story"),
            ],
            has_series_line=True,
            fallback_anchor_media_id="101",
            canonical_root_media_id="100",
        )

        default_vm = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="default")
        ).build_view_model(snapshot)
        no_character_vm = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="no_character")
        ).build_view_model(snapshot)
        curated_vm = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="curated")
        ).build_view_model(snapshot)

        default_sections = {section.key: section for section in default_vm.sections}
        no_character_sections = {section.key: section for section in no_character_vm.sections}
        curated_sections = {section.key: section for section in curated_vm.sections}
        self.assertEqual([entry["media_id"] for entry in default_vm.series_line_entries], ["100", "101"])
        self.assertEqual(
            [section.key for section in default_vm.sections],
            ["continuity_extras", "specials", "related_series"],
        )
        self.assertEqual(
            [section.key for section in no_character_vm.sections],
            ["continuity_extras", "specials", "related_series"],
        )
        self.assertEqual(
            [section.key for section in curated_vm.sections],
            ["continuity_extras", "specials", "related_series"],
        )
        self.assertEqual(default_sections["continuity_extras"].entries, [])
        self.assertEqual([entry["media_id"] for entry in default_sections["specials"].entries], ["207"])
        self.assertEqual([entry["media_id"] for entry in no_character_sections["specials"].entries], ["207"])

        self.assertEqual(
            [entry["media_id"] for entry in default_sections["related_series"].entries],
            ["204", "205", "206"],
        )
        self.assertEqual(
            [entry["media_id"] for entry in no_character_sections["related_series"].entries],
            ["204", "205"],
        )
        self.assertEqual(curated_sections["related_series"].title, "Spin-offs & Related")
        self.assertEqual([entry["media_id"] for entry in curated_sections["related_series"].entries], ["204"])
        self.assertEqual([entry["media_id"] for entry in curated_sections["specials"].entries], ["205"])


class AnimeFranchiseUiBuilderDelegationTests(SimpleTestCase):
    def test_builder_delegates_candidate_projection_to_shared_module(self):
        root = AnimeNode("100", "Series", "mal", "tv", "img", date(2010, 1, 1), [])
        snapshot = AnimeFranchiseSnapshot(
            root_node=root,
            nodes_by_media_id={"100": root},
            all_normalized_relations=[],
            continuity_component=[root],
            series_line=[root],
            direct_anchors=[root],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="100",
            canonical_root_media_id="100",
        )

        with patch("app.services.anime_franchise_ui_builder.build_franchise_candidates", return_value={}) as mock_projection:
            AnimeFranchiseUiBuilder(
                ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="default")
            ).build_view_model(snapshot)

        mock_projection.assert_called_once_with(snapshot)
