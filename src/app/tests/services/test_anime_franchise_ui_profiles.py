# ruff: noqa: D101,D102,D107
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_types import AnimeFranchiseCandidate, AnimeNode, AnimeRelation
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder
from app.services.anime_franchise_ui_policies import (
    BaseUiPolicy,
    UiPolicyStage,
    UiPolicySuite,
)
from app.services.anime_franchise_ui_policy_resolver import resolve_ui_policy_suite
from app.services.anime_franchise_ui_profiles import (
    BaseUiProfile,
    CuratedUiProfile,
    DefaultUiProfile,
    NoCharacterRelationsUiProfile,
    build_policy_suite_from_legacy_profile,
    get_ui_profile,
)


class FakeGraphBuilder:
    def __init__(self, nodes, continuity_ids=None):
        self.nodes = nodes
        self.continuity_ids = set(continuity_ids or nodes.keys())

    def build(self, root_media_id):
        return {
            media_id: self.nodes[media_id]
            for media_id in self.continuity_ids
        }

    def get_direct_neighbors(self, media_id):
        return self.nodes[str(media_id)].relations

    def ensure_node(self, media_id):
        return self.nodes[str(media_id)]


class PartialSectionsProfile(BaseUiProfile):
    key = "partial"

    def target_section_key(self, candidate, default_section_key):
        if default_section_key == "specials":
            return "missing_section_key"
        return default_section_key

    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series":
            return [candidates[-1], *candidates[:-1]] if candidates else []
        return candidates


class NoneSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "specials":
            return None
        return candidates


class TupleSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series":
            return tuple(candidates)
        return candidates


class DictSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series":
            return {"bad": "payload"}
        return candidates


class InvalidItemSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "specials":
            return [*candidates, "bad"]
        return candidates


class ForeignCandidateSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series":
            return [
                *candidates,
                AnimeFranchiseCandidate(
                    media_id="999",
                    title="Foreign Candidate",
                    image="img",
                    source="mal",
                    media_type="tv",
                    start_date=date(2019, 1, 1),
                    relation_type="spin_off",
                    is_current=False,
                    is_direct_from_series_line=True,
                    linked_series_line_media_id="100",
                    linked_series_line_index=0,
                ),
            ]
        return candidates


class RebuiltCandidateSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series" and candidates:
            original = candidates[0]
            rebuilt = AnimeFranchiseCandidate(
                media_id=original.media_id,
                title=original.title,
                image=original.image,
                source=original.source,
                media_type=original.media_type,
                start_date=original.start_date,
                relation_type=original.relation_type,
                is_current=original.is_current,
                is_direct_from_series_line=original.is_direct_from_series_line,
                linked_series_line_media_id=original.linked_series_line_media_id,
                linked_series_line_index=original.linked_series_line_index,
            )
            return [rebuilt, *candidates[1:]]
        return candidates


class DuplicateCandidateSortProfile(BaseUiProfile):
    def sort_section_candidates(self, section_key, candidates):
        if section_key == "related_series" and candidates:
            return [candidates[0], *candidates]
        return candidates


class HideSpecialMediaProfile(BaseUiProfile):
    key = "hide_special"
    hidden_media_types = frozenset({"special"})


class UiProfileRegistryTests(SimpleTestCase):
    def test_get_ui_profile_default(self):
        profile = get_ui_profile("default")
        self.assertIsInstance(profile, DefaultUiProfile)

    def test_get_ui_profile_no_character(self):
        profile = get_ui_profile("no_character")
        self.assertIsInstance(profile, NoCharacterRelationsUiProfile)

    def test_get_ui_profile_curated(self):
        profile = get_ui_profile("curated")
        self.assertIsInstance(profile, CuratedUiProfile)

    def test_get_ui_profile_unknown_raises_clear_error(self):
        with self.assertRaisesMessage(ValueError, "Unsupported UI profile 'unknown'"):
            get_ui_profile("unknown")


class UiProfileBehaviorTests(SimpleTestCase):
    def _candidate(self, *, media_id="10", title="Sample", relation_type="spin_off", media_type="tv"):
        return AnimeFranchiseCandidate(
            media_id=media_id,
            title=title,
            image="img",
            source="mal",
            media_type=media_type,
            start_date=date(2010, 1, 1),
            relation_type=relation_type,
            is_current=False,
            is_direct_from_series_line=True,
            linked_series_line_media_id="1",
            linked_series_line_index=0,
        )

    def test_default_profile_is_no_op(self):
        profile = DefaultUiProfile()
        candidate = self._candidate()

        self.assertTrue(profile.is_candidate_visible(candidate))
        self.assertEqual(profile.target_section_key(candidate, "related_series"), "related_series")
        self.assertEqual(profile.sort_section_candidates("related_series", [candidate]), [candidate])
        self.assertEqual(
            profile.section_title("related_series", "Related Series", [candidate]),
            "Related Series",
        )

    def test_no_character_profile_hides_character_relation(self):
        profile = NoCharacterRelationsUiProfile()
        self.assertFalse(profile.is_candidate_visible(self._candidate(relation_type="character")))
        self.assertTrue(profile.is_candidate_visible(self._candidate(relation_type="spin_off")))

    def test_hidden_media_types_hides_matching_media_type(self):
        profile = HideSpecialMediaProfile()
        self.assertFalse(profile.is_candidate_visible(self._candidate(media_type="special")))
        self.assertTrue(profile.is_candidate_visible(self._candidate(media_type="tv")))

    def test_hidden_titles_matching_is_case_insensitive_and_stripped(self):
        class HidePreviewProfile(BaseUiProfile):
            hidden_titles = frozenset({"  PREVIEW SHORT "})

        profile = HidePreviewProfile()
        self.assertFalse(profile.is_candidate_visible(self._candidate(title="preview short")))
        self.assertFalse(profile.is_candidate_visible(self._candidate(title="  Preview Short  ")))
        self.assertTrue(profile.is_candidate_visible(self._candidate(title="Preview Long")))

    def test_curated_profile_supports_hide_reclassify_sort_and_title(self):
        profile = CuratedUiProfile()

        hidden_character = self._candidate(media_id="11", relation_type="character")
        hidden_title = self._candidate(media_id="12", title="Preview short")
        moved = self._candidate(media_id="13", relation_type="spin_off", media_type="special")
        regular = self._candidate(media_id="14", relation_type="parent_story", media_type="tv")

        self.assertFalse(profile.is_candidate_visible(hidden_character))
        self.assertFalse(profile.is_candidate_visible(hidden_title))
        self.assertEqual(profile.target_section_key(moved, "related_series"), "specials")
        self.assertEqual(profile.target_section_key(regular, "related_series"), "related_series")

        unsorted_related = [regular, moved]
        sorted_related = profile.sort_section_candidates("related_series", unsorted_related)
        self.assertEqual([candidate.media_id for candidate in sorted_related], ["13", "14"])

        self.assertEqual(
            profile.section_title("related_series", "Related Series", sorted_related),
            "Spin-offs & Related",
        )


class UiBuilderRobustnessTests(SimpleTestCase):
    def _nodes(self):
        return {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "200", "sequel"),
                    AnimeRelation("100", "201", "side_story"),
                    AnimeRelation("100", "204", "spin_off"),
                    AnimeRelation("100", "207", "character"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "200": AnimeNode("200", "Movie Sequel", "mal", "movie", "img", date(2011, 2, 1)),
            "201": AnimeNode("201", "OVA Side Story", "mal", "ova", "img", date(2011, 3, 1)),
            "204": AnimeNode("204", "Spin Off", "mal", "tv", "img", date(2011, 4, 1)),
            "207": AnimeNode("207", "Character Story", "mal", "special", "img", date(2011, 5, 1)),
        }

    def test_builder_handles_missing_or_unknown_sections_without_key_error(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(PartialSectionsProfile())),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}

        self.assertEqual([entry["media_id"] for entry in sections["specials"].entries], ["201"])
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["207", "204"])

    def test_sort_section_candidates_accepts_none_as_empty(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(NoneSortProfile())),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}
        self.assertEqual(sections["specials"].entries, [])

    def test_sort_section_candidates_accepts_tuple(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(TupleSortProfile())),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["204", "207"])

    def test_sort_section_candidates_rejects_invalid_container_type(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(DictSortProfile())),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("DictSortProfile", message)
        self.assertIn("related_series", message)
        self.assertIn("got dict", message)

    def test_sort_section_candidates_rejects_invalid_item_type(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(InvalidItemSortProfile())),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("InvalidItemSortProfile", message)
        self.assertIn("specials", message)
        self.assertIn("got str", message)

    def test_sort_section_candidates_rejects_foreign_candidates(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(ForeignCandidateSortProfile())),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("ForeignCandidateSortProfile", message)
        self.assertIn("related_series", message)
        self.assertIn("999", message)
        self.assertIn("original input candidate objects", message)

    def test_sort_section_candidates_rejects_duplicate_candidates(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(DuplicateCandidateSortProfile())),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("DuplicateCandidateSortProfile", message)
        self.assertIn("related_series", message)
        self.assertIn("duplicate", message)

    def test_sort_section_candidates_rejects_rebuilt_candidate_with_same_media_id(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(RebuiltCandidateSortProfile())),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("RebuiltCandidateSortProfile", message)
        self.assertIn("related_series", message)
        self.assertIn("204", message)
        self.assertIn("original input candidate objects", message)


class UiServiceIntegrationTests(SimpleTestCase):
    def _nodes(self):
        return {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "204", "spin_off"),
                    AnimeRelation("100", "205", "spin_off"),
                    AnimeRelation("100", "206", "character"),
                    AnimeRelation("100", "207", "side_story"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
            "205": AnimeNode("205", "Spin Off Special", "mal", "special", "img", date(2011, 5, 1)),
            "206": AnimeNode("206", "Character Story", "mal", "special", "img", date(2011, 6, 1)),
            "207": AnimeNode("207", "Preview short", "mal", "ova", "img", date(2011, 7, 1)),
        }

    def test_service_build_default_profile_still_works(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"})
        )
        view_model = service.build("101")

        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204", "205", "206"])

    def test_service_build_curated_profile_applies_policy(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_profile_key="curated",
        )
        view_model = service.build("101")

        sections = {section.key: section for section in view_model.sections}
        self.assertEqual(sections["related_series"].title, "Spin-offs & Related")
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["204"])
        self.assertEqual([entry["media_id"] for entry in sections["specials"].entries], ["205"])

    def test_service_build_no_character_profile_applies_policy(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_profile_key="no_character",
        )
        view_model = service.build("101")

        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204", "205"])


class UiPolicySuiteBehaviorTests(SimpleTestCase):
    def _nodes(self):
        return {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "204", "spin_off"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
        }

    def test_visibility_hide_wins_with_multiple_policies(self):
        class AllowAllVisibilityPolicy(BaseUiPolicy):
            key = "allow_all"
            stage = UiPolicyStage.VISIBILITY
            priority = 10

            def is_candidate_visible(self, candidate):
                return True

        class HideSpinOffPolicy(BaseUiPolicy):
            key = "hide_spin_off"
            stage = UiPolicyStage.VISIBILITY
            priority = 20

            def is_candidate_visible(self, candidate):
                return candidate.relation_type != "spin_off"

        suite = UiPolicySuite(policies=(AllowAllVisibilityPolicy(), HideSpinOffPolicy()))
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=suite),
        )

        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual(related.entries, [])

    def test_section_target_last_write_wins(self):
        class MoveToSpecialsPolicy(BaseUiPolicy):
            key = "to_specials"
            stage = UiPolicyStage.SECTION_TARGET
            priority = 10

            def target_section_key(self, candidate, current_section_key):
                if candidate.relation_type == "spin_off":
                    return "specials"
                return current_section_key

        class MoveBackToRelatedPolicy(BaseUiPolicy):
            key = "back_to_related"
            stage = UiPolicyStage.SECTION_TARGET
            priority = 20

            def target_section_key(self, candidate, current_section_key):
                if candidate.relation_type == "spin_off":
                    return "related_series"
                return current_section_key

        suite = UiPolicySuite(policies=(MoveToSpecialsPolicy(), MoveBackToRelatedPolicy()))
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=suite),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["204"])
        self.assertEqual(sections["specials"].entries, [])

    def test_section_title_last_non_empty_wins(self):
        class FirstTitlePolicy(BaseUiPolicy):
            key = "first_title"
            stage = UiPolicyStage.SECTION_TITLE
            priority = 10

            def section_title(self, section_key, current_title, candidates):
                if section_key == "related_series":
                    return "First"
                return current_title

        class EmptyTitlePolicy(BaseUiPolicy):
            key = "empty_title"
            stage = UiPolicyStage.SECTION_TITLE
            priority = 20

            def section_title(self, section_key, current_title, candidates):
                if section_key == "related_series":
                    return ""
                return current_title

        class FinalTitlePolicy(BaseUiPolicy):
            key = "final_title"
            stage = UiPolicyStage.SECTION_TITLE
            priority = 30

            def section_title(self, section_key, current_title, candidates):
                if section_key == "related_series":
                    return "Final"
                return current_title

        suite = UiPolicySuite(policies=(FirstTitlePolicy(), EmptyTitlePolicy(), FinalTitlePolicy()))
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=suite),
        )

        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual(related.title, "Final")

    def test_builder_executes_stages_in_declared_order(self):
        calls = []

        class TraceVisibilityPolicy(BaseUiPolicy):
            key = "trace_visibility"
            stage = UiPolicyStage.VISIBILITY

            def is_candidate_visible(self, candidate):
                calls.append("visibility")
                return True

        class TraceTargetPolicy(BaseUiPolicy):
            key = "trace_target"
            stage = UiPolicyStage.SECTION_TARGET

            def target_section_key(self, candidate, current_section_key):
                calls.append("section_target")
                return current_section_key

        class TraceSortPolicy(BaseUiPolicy):
            key = "trace_sort"
            stage = UiPolicyStage.SORT

            def sort_section_candidates(self, section_key, candidates):
                calls.append("sort")
                return candidates

        class TraceTitlePolicy(BaseUiPolicy):
            key = "trace_title"
            stage = UiPolicyStage.SECTION_TITLE

            def section_title(self, section_key, current_title, candidates):
                calls.append("section_title")
                return current_title

        suite = UiPolicySuite(
            policies=(
                TraceVisibilityPolicy(),
                TraceTargetPolicy(),
                TraceSortPolicy(),
                TraceTitlePolicy(),
            )
        )
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=suite),
        )

        service.build("101")
        first_seen = []
        for stage in calls:
            if stage not in first_seen:
                first_seen.append(stage)
        self.assertEqual(first_seen, ["visibility", "section_target", "sort", "section_title"])

    def test_native_policy_suite_unknown_section_falls_back_to_default(self):
        class UnknownSectionPolicy(BaseUiPolicy):
            key = "unknown_section"
            stage = UiPolicyStage.SECTION_TARGET

            def target_section_key(self, candidate, current_section_key):
                if candidate.relation_type == "spin_off":
                    return "unknown"
                return current_section_key

        suite = UiPolicySuite(policies=(UnknownSectionPolicy(),))
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=suite),
        )
        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204"])

    def test_native_sort_policy_invalid_container_has_clear_error(self):
        class InvalidNativeSortPolicy(BaseUiPolicy):
            key = "invalid_native_sort"
            stage = UiPolicyStage.SORT

            def sort_section_candidates(self, section_key, candidates):
                if section_key == "related_series":
                    return {"bad": "payload"}
                return candidates

        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(
                ui_policy_suite=UiPolicySuite(policies=(InvalidNativeSortPolicy(),))
            ),
        )

        with self.assertRaises(TypeError) as exc:
            service.build("101")
        message = str(exc.exception)
        self.assertIn("UI policy/profile", message)
        self.assertIn("InvalidNativeSortPolicy", message)
        self.assertIn("related_series", message)
        self.assertIn("got dict", message)


class LegacyProfileSuiteAdapterTests(SimpleTestCase):
    def test_profile_to_suite_includes_hide_and_legacy_policies(self):
        class MixedProfile(BaseUiProfile):
            hidden_relation_types = frozenset({"character"})
            hidden_media_types = frozenset({"special"})
            hidden_titles = frozenset({"Preview"})

        suite = build_policy_suite_from_legacy_profile(MixedProfile())
        keys = [policy.key for policy in suite.policies]

        self.assertIn("hide_relation_types", keys)
        self.assertIn("hide_media_types", keys)
        self.assertIn("hide_titles", keys)
        self.assertIn("legacy_profile_section_target", keys)
        self.assertIn("legacy_profile_sort", keys)
        self.assertIn("legacy_profile_section_title", keys)
        self.assertNotIn("legacy_profile_visibility", keys)

    def test_profile_to_suite_omits_empty_hide_policies(self):
        suite = build_policy_suite_from_legacy_profile(DefaultUiProfile())
        keys = [policy.key for policy in suite.policies]

        self.assertNotIn("hide_relation_types", keys)
        self.assertNotIn("hide_media_types", keys)
        self.assertNotIn("hide_titles", keys)
        self.assertEqual(
            keys,
            [
                "legacy_profile_section_target",
                "legacy_profile_sort",
                "legacy_profile_section_title",
            ],
        )

    def test_profile_to_suite_skips_visibility_wrapper_for_default_visibility(self):
        suite = build_policy_suite_from_legacy_profile(DefaultUiProfile())
        visibility_policies = [
            policy
            for policy in suite.policies
            if policy.stage == UiPolicyStage.VISIBILITY
        ]
        self.assertEqual(visibility_policies, [])

    def test_visibility_wrapper_is_used_when_profile_overrides_visibility(self):
        class AlwaysVisibleProfile(BaseUiProfile):
            hidden_relation_types = frozenset({"spin_off"})

            def is_candidate_visible(self, candidate):
                return True

        profile = AlwaysVisibleProfile()
        suite = build_policy_suite_from_legacy_profile(profile)
        keys = [policy.key for policy in suite.policies]

        self.assertNotIn("hide_relation_types", keys)
        self.assertIn("legacy_profile_visibility", keys)
        self.assertEqual(
            [
                policy.key
                for policy in suite.policies
                if policy.stage == UiPolicyStage.VISIBILITY
            ],
            ["legacy_profile_visibility"],
        )

    def test_visibility_override_with_hidden_fields_keeps_legacy_semantics_in_builder(self):
        class AlwaysVisibleProfile(BaseUiProfile):
            hidden_relation_types = frozenset({"spin_off"})

            def is_candidate_visible(self, candidate):
                return True

        nodes = {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "204", "spin_off"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
        }
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(nodes, continuity_ids={"100", "101"}),
            ui_builder=AnimeFranchiseUiBuilder(ui_policy_suite=build_policy_suite_from_legacy_profile(AlwaysVisibleProfile())),
        )

        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204"])


class UiBuilderResolutionPriorityTests(SimpleTestCase):
    def _nodes(self):
        return {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "204", "spin_off"),
                    AnimeRelation("100", "206", "character"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
            "206": AnimeNode("206", "Character Story", "mal", "special", "img", date(2011, 6, 1)),
        }

    def test_ui_policy_suite_has_highest_priority_over_ui_profile(self):
        class HideSpinOffPolicy(BaseUiPolicy):
            key = "hide_spin_off"
            stage = UiPolicyStage.VISIBILITY

            def is_candidate_visible(self, candidate):
                return candidate.relation_type != "spin_off"

        builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=UiPolicySuite(policies=(HideSpinOffPolicy(),)),
        )
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=builder,
        )
        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["206"])

    def test_ui_profile_has_priority_over_ui_profile_key(self):
        builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile=NoCharacterRelationsUiProfile()),
        )
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_builder=builder,
        )
        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204"])
