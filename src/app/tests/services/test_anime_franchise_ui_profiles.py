# ruff: noqa: D101,D102,D107
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_types import AnimeFranchiseCandidate, AnimeNode, AnimeRelation
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder
from app.services.anime_franchise_ui_profiles import (
    BaseUiProfile,
    CuratedUiProfile,
    DefaultUiProfile,
    NoCharacterRelationsUiProfile,
    get_ui_profile,
)


class FakeGraphBuilder:
    def __init__(self, nodes):
        self.nodes = nodes

    def build(self, root_media_id):
        return self.nodes

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
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=PartialSectionsProfile()),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}

        self.assertEqual([entry["media_id"] for entry in sections["specials"].entries], ["201"])
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["207", "204"])

    def test_sort_section_candidates_accepts_none_as_empty(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=NoneSortProfile()),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}
        self.assertEqual(sections["specials"].entries, [])

    def test_sort_section_candidates_accepts_tuple(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=TupleSortProfile()),
        )

        view_model = service.build("101")
        sections = {section.key: section for section in view_model.sections}
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["204", "207"])

    def test_sort_section_candidates_rejects_invalid_container_type(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=DictSortProfile()),
        )

        with self.assertRaisesRegex(
            TypeError,
            "DictSortProfile.*related_series.*got dict",
        ):
            service.build("101")

    def test_sort_section_candidates_rejects_invalid_item_type(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=InvalidItemSortProfile()),
        )

        with self.assertRaisesRegex(
            TypeError,
            "InvalidItemSortProfile.*specials.*got str",
        ):
            service.build("101")

    def test_sort_section_candidates_rejects_foreign_candidates(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=ForeignCandidateSortProfile()),
        )

        with self.assertRaisesRegex(
            TypeError,
            "ForeignCandidateSortProfile.*related_series.*999.*original input candidate objects",
        ):
            service.build("101")

    def test_sort_section_candidates_rejects_duplicate_candidates(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=DuplicateCandidateSortProfile()),
        )

        with self.assertRaisesRegex(
            TypeError,
            "DuplicateCandidateSortProfile.*related_series.*duplicate",
        ):
            service.build("101")

    def test_sort_section_candidates_rejects_rebuilt_candidate_with_same_media_id(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_builder=AnimeFranchiseUiBuilder(ui_profile=RebuiltCandidateSortProfile()),
        )

        with self.assertRaisesRegex(
            TypeError,
            "RebuiltCandidateSortProfile.*related_series.*204.*original input candidate objects",
        ):
            service.build("101")


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
        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(self._nodes()))
        view_model = service.build("101")

        related = next(section for section in view_model.sections if section.key == "related_series")
        self.assertEqual([entry["media_id"] for entry in related.entries], ["204", "205", "206"])

    def test_service_build_curated_profile_applies_policy(self):
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes()),
            ui_profile_key="curated",
        )
        view_model = service.build("101")

        sections = {section.key: section for section in view_model.sections}
        self.assertEqual(sections["related_series"].title, "Spin-offs & Related")
        self.assertEqual([entry["media_id"] for entry in sections["related_series"].entries], ["204"])
        self.assertEqual([entry["media_id"] for entry in sections["specials"].entries], ["205"])
