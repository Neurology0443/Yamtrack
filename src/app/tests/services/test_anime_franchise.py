# ruff: noqa: D101,D102,D107,ARG002,E501,I001
from datetime import date
from unittest.mock import patch
from django.test import SimpleTestCase

from app.providers import mal
from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


class FakeGraphBuilder:
    def __init__(self, nodes):
        self.nodes = nodes

    def build(self, root_media_id):
        continuity_relations = {"prequel", "sequel"}
        root_id = str(root_media_id)
        queue = [root_id]
        visited = set()
        continuity_nodes = {}

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = self.nodes[node_id]
            continuity_nodes[node_id] = node
            for relation in node.relations:
                if relation.relation_type not in continuity_relations:
                    continue
                target_id = str(relation.target_media_id)
                if target_id in self.nodes and target_id not in visited:
                    queue.append(target_id)

        return continuity_nodes

    def get_direct_neighbors(self, media_id):
        return self.nodes[str(media_id)].relations

    def ensure_node(self, media_id):
        return self.nodes[str(media_id)]


class AnimeFranchiseServiceTests(SimpleTestCase):
    def setUp(self):
        self.nodes = {
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
                    AnimeRelation("100", "202", "summary"),
                    AnimeRelation("100", "203", "side_story"),
                    AnimeRelation("100", "204", "spin_off"),
                    AnimeRelation("100", "205", "other"),
                    AnimeRelation("100", "206", "cm"),
                    AnimeRelation("100", "207", "character"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2012, 1, 1),
                relations=[
                    AnimeRelation("101", "100", "prequel"),
                    AnimeRelation("101", "102", "sequel"),
                    AnimeRelation("101", "208", "sequel"),
                    AnimeRelation("101", "209", "prequel"),
                    AnimeRelation("101", "210", "sequel"),
                    AnimeRelation("101", "212", "sequel"),
                    AnimeRelation("101", "211", "pv"),
                ],
            ),
            "102": AnimeNode(
                media_id="102",
                title="Series S3",
                source="mal",
                media_type="tv",
                image="img-102",
                start_date=date(2014, 1, 1),
                relations=[AnimeRelation("102", "101", "prequel")],
            ),
            "200": AnimeNode("200", "Movie Sequel", "mal", "movie", "img", date(2011, 1, 1)),
            "201": AnimeNode("201", "OVA Side Story", "mal", "ova", "img", date(2011, 2, 1)),
            "202": AnimeNode("202", "Movie Summary", "mal", "movie", "img", date(2011, 3, 1)),
            "203": AnimeNode("203", "ONA Side Story", "mal", "ona", "img", date(2011, 4, 1)),
            "204": AnimeNode("204", "Spin Off", "mal", "tv", "img", date(2011, 5, 1)),
            "205": AnimeNode("205", "Other Noise", "mal", "movie", "img", date(2011, 6, 1)),
            "206": AnimeNode("206", "Commercial", "mal", "cm", "img", date(2011, 7, 1)),
            "207": AnimeNode("207", "Character Story", "mal", "special", "img", date(2011, 8, 1)),
            "208": AnimeNode("208", "ONA Sequel", "mal", "ona", "img", date(2012, 2, 1)),
            "209": AnimeNode("209", "OVA Prequel", "mal", "ova", "img", date(2009, 12, 1)),
            "210": AnimeNode("210", "Special Sequel", "mal", "special", "img", date(2012, 3, 1)),
            "211": AnimeNode("211", "PV", "mal", "pv", "img", date(2012, 4, 1)),
            "212": AnimeNode("212", "TV Special Sequel", "mal", "tv_special", "img", date(2012, 5, 1)),
        }

    def _build(self):
        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(self.nodes))
        return service.build("101")

    @staticmethod
    def _sections_by_key(payload):
        return {section["key"]: section for section in payload.sections}

    @staticmethod
    def _section_media_ids(sections, key):
        return [entry["media_id"] for entry in sections.get(key, {}).get("entries", [])]

    def test_series_line_contains_only_tv(self):
        payload = self._build()
        self.assertEqual(
            [entry["media_id"] for entry in payload.series["entries"]],
            ["100", "101", "102"],
        )

    def test_continuity_extras_collects_non_tv_prequel_sequel(self):
        payload = self._build()
        continuity = next(section for section in payload.sections if section["key"] == "continuity_extras")
        self.assertCountEqual(
            [entry["media_id"] for entry in continuity["entries"]],
            ["209", "200", "210", "208", "212"],
        )

    def test_continuity_extras_promotes_transitive_movie_chain_from_series_root(self):
        nodes = {
            "100": AnimeNode("100", "Season 1", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "101", "sequel")]),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("101", "100", "prequel"), AnimeRelation("101", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Movie 1",
                "mal",
                "movie",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("200", "101", "prequel"), AnimeRelation("200", "201", "sequel")],
            ),
            "201": AnimeNode(
                "201",
                "Movie 2",
                "mal",
                "movie",
                "img",
                date(2023, 1, 1),
                [AnimeRelation("201", "200", "prequel"), AnimeRelation("201", "202", "sequel")],
            ),
            "202": AnimeNode("202", "Movie 3", "mal", "movie", "img", date(2024, 1, 1), [AnimeRelation("202", "201", "prequel")]),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("101")
        sections = {section["key"]: section for section in payload.sections}

        self.assertEqual([entry["media_id"] for entry in payload.series["entries"]], ["100", "101"])
        self.assertEqual(
            [entry["media_id"] for entry in sections["continuity_extras"]["entries"]],
            ["200", "201", "202"],
        )
        continuity_entries = {
            entry["media_id"]: entry
            for entry in sections["continuity_extras"]["entries"]
        }
        self.assertEqual(continuity_entries["201"]["linked_series_line_media_id"], "101")
        self.assertEqual(continuity_entries["202"]["linked_series_line_media_id"], "101")
        self.assertEqual(continuity_entries["201"]["linked_series_line_index"], 1)
        self.assertEqual(continuity_entries["202"]["linked_series_line_index"], 1)
        all_section_ids = [
            entry["media_id"]
            for section in payload.sections
            for entry in section["entries"]
        ]
        self.assertEqual(len(all_section_ids), len(set(all_section_ids)))
        self.assertFalse(
            {"200", "201", "202"}.intersection(
                {entry["media_id"] for entry in payload.series["entries"]}
            )
        )

    def test_promoted_target_prefers_earliest_series_anchor_before_shorter_depth(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Season 1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("100", "101", "sequel"), AnimeRelation("100", "200", "sequel")],
            ),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("101", "100", "prequel"), AnimeRelation("101", "102", "sequel")],
            ),
            "102": AnimeNode(
                "102",
                "Season 3",
                "mal",
                "tv",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("102", "101", "prequel"), AnimeRelation("102", "300", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Movie A",
                "mal",
                "movie",
                "img",
                date(2022, 6, 1),
                [AnimeRelation("200", "300", "sequel"), AnimeRelation("200", "100", "prequel")],
            ),
            "300": AnimeNode(
                "300",
                "Movie B",
                "mal",
                "movie",
                "img",
                date(2023, 1, 1),
                [AnimeRelation("300", "200", "prequel"), AnimeRelation("300", "102", "prequel")],
            ),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("102")
        sections = {section["key"]: section for section in payload.sections}
        continuity_entries = {
            entry["media_id"]: entry
            for entry in sections["continuity_extras"]["entries"]
        }

        self.assertEqual(continuity_entries["300"]["linked_series_line_media_id"], "100")
        self.assertEqual(continuity_entries["300"]["linked_series_line_index"], 0)

    def test_specials_do_not_become_transitive_when_promoted_continuity_exists(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Season 1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("100", "101", "sequel"), AnimeRelation("100", "400", "side_story")],
            ),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("101", "100", "prequel"), AnimeRelation("101", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Movie 1",
                "mal",
                "movie",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("200", "201", "sequel"), AnimeRelation("200", "101", "prequel")],
            ),
            "201": AnimeNode("201", "Movie 2", "mal", "movie", "img", date(2023, 1, 1), [AnimeRelation("201", "200", "prequel")]),
            "400": AnimeNode(
                "400",
                "OVA 1",
                "mal",
                "ova",
                "img",
                date(2021, 6, 1),
                [AnimeRelation("400", "401", "side_story"), AnimeRelation("400", "100", "parent_story")],
            ),
            "401": AnimeNode("401", "OVA 2", "mal", "ova", "img", date(2021, 7, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("101")
        sections = {section["key"]: section for section in payload.sections}
        specials_ids = [entry["media_id"] for entry in sections["specials"]["entries"]]

        self.assertIn("400", specials_ids)
        self.assertNotIn("401", specials_ids)

    def test_related_series_do_not_become_transitive_when_promoted_continuity_exists(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Season 1",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [AnimeRelation("100", "101", "sequel"), AnimeRelation("100", "500", "spin_off")],
            ),
            "101": AnimeNode(
                "101",
                "Season 2",
                "mal",
                "tv",
                "img",
                date(2021, 1, 1),
                [AnimeRelation("101", "100", "prequel"), AnimeRelation("101", "200", "sequel")],
            ),
            "200": AnimeNode(
                "200",
                "Movie 1",
                "mal",
                "movie",
                "img",
                date(2022, 1, 1),
                [AnimeRelation("200", "101", "prequel"), AnimeRelation("200", "201", "sequel")],
            ),
            "201": AnimeNode("201", "Movie 2", "mal", "movie", "img", date(2023, 1, 1), [AnimeRelation("201", "200", "prequel")]),
            "500": AnimeNode(
                "500",
                "Related A",
                "mal",
                "movie",
                "img",
                date(2021, 6, 1),
                [AnimeRelation("500", "501", "spin_off")],
            ),
            "501": AnimeNode("501", "Related B", "mal", "movie", "img", date(2021, 7, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("101")
        sections = {section["key"]: section for section in payload.sections}
        related_ids = [entry["media_id"] for entry in sections["related_series"]["entries"]]

        self.assertIn("500", related_ids)
        self.assertNotIn("501", related_ids)

    def test_specials_selective_and_excludes_ona(self):
        payload = self._build()
        specials = next(section for section in payload.sections if section["key"] == "specials")
        self.assertEqual([entry["media_id"] for entry in specials["entries"]], ["201", "202"])
        self.assertNotIn("203", [entry["media_id"] for entry in specials["entries"]])

    def test_expected_entries_are_grouped_in_target_sections(self):
        payload = self._build()
        sections = {section["key"]: section for section in payload.sections}

        continuity_ids = {entry["media_id"] for entry in sections["continuity_extras"]["entries"]}
        self.assertIn("200", continuity_ids)  # movie sequel
        self.assertIn("209", continuity_ids)  # ova prequel
        self.assertIn("208", continuity_ids)  # ona sequel
        self.assertIn("210", continuity_ids)  # special sequel
        self.assertIn("212", continuity_ids)  # tv_special sequel

        specials_ids = {entry["media_id"] for entry in sections["specials"]["entries"]}
        self.assertIn("201", specials_ids)  # side_story + ova
        self.assertIn("202", specials_ids)  # summary + movie
        self.assertNotIn("203", specials_ids)  # side_story + ona excluded

    def test_related_series_direct_only(self):
        payload = self._build()
        related = next(section for section in payload.sections if section["key"] == "related_series")
        self.assertEqual([entry["media_id"] for entry in related["entries"]], ["204", "207"])

    def test_long_tv_spinoff_moves_to_spin_offs(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "spin_off")]),
            "200": AnimeNode("200", "Long Spin Off", "mal", "tv", "img", date(2021, 1, 1), [], runtime_minutes=45),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertEqual(self._section_media_ids(sections, "spin_offs"), ["200"])
        self.assertNotIn("200", self._section_media_ids(sections, "related_series"))

    def test_short_tv_spinoff_stays_in_related_series(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "spin_off")]),
            "200": AnimeNode("200", "Short Spin Off", "mal", "tv", "img", date(2021, 1, 1), [], runtime_minutes=24),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertEqual(self._section_media_ids(sections, "related_series"), ["200"])
        self.assertNotIn("200", self._section_media_ids(sections, "spin_offs"))

    def test_tv_side_story_moves_from_specials_to_related_series(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "side_story")]),
            "200": AnimeNode("200", "TV Side Story", "mal", "tv", "img", date(2021, 1, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertIn("200", self._section_media_ids(sections, "related_series"))
        self.assertNotIn("200", self._section_media_ids(sections, "specials"))
        self.assertNotIn("200", self._section_media_ids(sections, "ignored"))

    def test_non_tv_side_story_stays_in_specials(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "side_story")]),
            "200": AnimeNode("200", "OVA Side Story", "mal", "ova", "img", date(2021, 1, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertIn("200", self._section_media_ids(sections, "specials"))
        self.assertNotIn("200", self._section_media_ids(sections, "related_series"))

    def test_short_side_story_moves_from_specials_to_related_series(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "side_story")]),
            "200": AnimeNode("200", "Short OVA Side Story", "mal", "ova", "img", date(2021, 1, 1), [], runtime_minutes=12),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertIn("200", self._section_media_ids(sections, "related_series"))
        self.assertNotIn("200", self._section_media_ids(sections, "specials"))
        self.assertNotIn("200", self._section_media_ids(sections, "ignored"))

    def test_side_story_runtime_15_or_more_stays_in_specials(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "side_story")]),
            "200": AnimeNode("200", "Longer OVA Side Story", "mal", "ova", "img", date(2021, 1, 1), [], runtime_minutes=15),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertIn("200", self._section_media_ids(sections, "specials"))
        self.assertNotIn("200", self._section_media_ids(sections, "related_series"))

    def test_side_story_unknown_runtime_does_not_trigger_short_runtime_reclassification(self):
        nodes = {
            "100": AnimeNode("100", "Root", "mal", "tv", "img", date(2020, 1, 1), [AnimeRelation("100", "200", "side_story")]),
            "200": AnimeNode("200", "Unknown Runtime OVA Side Story", "mal", "ova", "img", date(2021, 1, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertIn("200", self._section_media_ids(sections, "specials"))
        self.assertNotIn("200", self._section_media_ids(sections, "related_series"))

    def test_alternatives_section_collects_version_and_setting(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Root",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [
                    AnimeRelation("100", "201", "alternative_version"),
                    AnimeRelation("100", "202", "alternative_setting"),
                ],
            ),
            "201": AnimeNode("201", "Alt Version", "mal", "movie", "img", date(2021, 1, 1), []),
            "202": AnimeNode("202", "Alt Setting", "mal", "movie", "img", date(2021, 2, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)
        alternatives_ids = self._section_media_ids(sections, "alternatives")

        self.assertCountEqual(alternatives_ids, ["201", "202"])
        self.assertNotIn("201", self._section_media_ids(sections, "related_series"))
        self.assertNotIn("202", self._section_media_ids(sections, "related_series"))

    def test_alternatives_section_orders_version_before_setting(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Root",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [
                    AnimeRelation("100", "202", "alternative_setting"),
                    AnimeRelation("100", "201", "alternative_version"),
                ],
            ),
            "201": AnimeNode("201", "Alt Version", "mal", "movie", "img", date(2021, 1, 1), []),
            "202": AnimeNode("202", "Alt Setting", "mal", "movie", "img", date(2021, 2, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        self.assertEqual(
            self._section_media_ids(sections, "alternatives"),
            ["201", "202"],
        )
        self.assertNotIn("201", self._section_media_ids(sections, "related_series"))
        self.assertNotIn("202", self._section_media_ids(sections, "related_series"))

    def test_other_related_entries_remain_in_related_series(self):
        payload = self._build()
        sections = self._sections_by_key(payload)

        related_ids = self._section_media_ids(sections, "related_series")
        self.assertIn("207", related_ids)
        self.assertNotIn("207", self._section_media_ids(sections, "spin_offs"))
        self.assertNotIn("207", self._section_media_ids(sections, "alternatives"))
        self.assertGreater(len(related_ids), 0)

    def test_refined_related_section_order_spin_offs_then_alternatives_then_related(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Root",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [
                    AnimeRelation("100", "201", "spin_off"),
                    AnimeRelation("100", "202", "alternative_version"),
                    AnimeRelation("100", "203", "character"),
                ],
            ),
            "201": AnimeNode("201", "Long Spin Off", "mal", "tv", "img", date(2021, 1, 1), [], runtime_minutes=45),
            "202": AnimeNode("202", "Alt Version", "mal", "movie", "img", date(2021, 2, 1), []),
            "203": AnimeNode("203", "Residual Related", "mal", "special", "img", date(2021, 3, 1), []),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        section_keys = [section["key"] for section in payload.sections]

        self.assertLess(section_keys.index("spin_offs"), section_keys.index("alternatives"))
        self.assertLess(section_keys.index("alternatives"), section_keys.index("related_series"))

    def test_ambiguous_spin_off_and_alternative_version_prefers_spin_offs(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "Root",
                "mal",
                "tv",
                "img",
                date(2020, 1, 1),
                [
                    AnimeRelation("100", "210", "spin_off"),
                    AnimeRelation("100", "210", "alternative_version"),
                ],
            ),
            "210": AnimeNode("210", "Ambiguous", "mal", "tv", "img", date(2021, 1, 1), [], runtime_minutes=48),
        }
        payload = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes)).build("100")
        sections = self._sections_by_key(payload)

        # Spin Offs wins because the long-TV spin-off refinement runs after alternatives and can overwrite section_key.
        self.assertEqual(self._section_media_ids(sections, "spin_offs"), ["210"])
        self.assertNotIn("210", self._section_media_ids(sections, "alternatives"))
        self.assertNotIn("210", self._section_media_ids(sections, "related_series"))

    def test_noise_is_ignored_and_no_duplicates(self):
        payload = self._build()
        visible_section_ids = []
        ignored_section_ids = []
        for section in payload.sections:
            ids = [entry["media_id"] for entry in section["entries"]]
            if section["key"] == "ignored":
                ignored_section_ids.extend(ids)
                continue
            visible_section_ids.extend(ids)

        self.assertNotIn("205", visible_section_ids)
        self.assertNotIn("206", visible_section_ids)
        self.assertNotIn("211", visible_section_ids)
        self.assertIn("205", ignored_section_ids)
        self.assertIn("206", ignored_section_ids)
        self.assertIn("211", ignored_section_ids)

        all_section_ids = visible_section_ids + ignored_section_ids
        self.assertEqual(len(all_section_ids), len(set(all_section_ids)))

        series_ids = {entry["media_id"] for entry in payload.series["entries"]}
        self.assertFalse(series_ids.intersection(set(all_section_ids)))

    def test_no_series_line_fallback_uses_seed_anchor_for_direct_only_rules(self):
        movie_root = AnimeNode(
            media_id="500",
            title="Movie Root",
            source="mal",
            media_type="movie",
            image="img",
            start_date=date(2018, 1, 1),
            relations=[AnimeRelation("500", "501", "spin_off")],
        )
        spin_off = AnimeNode(
            media_id="501",
            title="Spin Off Movie",
            source="mal",
            media_type="movie",
            image="img",
            start_date=date(2019, 1, 1),
            relations=[],
        )
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder({"500": movie_root, "501": spin_off}),
        )

        payload = service.build("500")
        self.assertEqual(payload.series["entries"], [])
        related = next(section for section in payload.sections if section["key"] == "related_series")
        self.assertEqual([entry["media_id"] for entry in related["entries"]], ["501"])
        self.assertEqual(related["entries"][0]["linked_series_line_media_id"], "500")
        self.assertEqual(related["entries"][0]["linked_series_line_index"], 0)
        self.assertNotIn(
            "500",
            [entry["media_id"] for section in payload.sections for entry in section["entries"]],
        )

    def test_payload_exposes_anime_media_type_for_future_badges(self):
        payload = self._build()
        series_anime_media_types = {entry["anime_media_type"] for entry in payload.series["entries"]}
        self.assertEqual(series_anime_media_types, {"tv"})

        related = next(
            section for section in payload.sections if section["key"] == "related_series"
        )
        target = next(entry for entry in related["entries"] if entry["media_id"] == "204")
        self.assertEqual(target["anime_media_type"], "tv")
        self.assertEqual(target["relation_type"], "spin_off")

    def test_relation_type_normalization_helper(self):
        self.assertEqual(mal.normalize_relation_type("Side Story"), "side_story")
        self.assertEqual(mal.normalize_relation_type("full-story"), "full_story")

    def test_existing_section_classification_still_works_for_root_outside_series_line(self):
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
                [AnimeRelation("200", "300", "sequel"), AnimeRelation("200", "100", "prequel")],
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
        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes))

        payload = service.build("200")
        continuity = next(section for section in payload.sections if section["key"] == "continuity_extras")

        self.assertIn("300", [entry["media_id"] for entry in continuity["entries"]])

    def test_ambiguous_other_plus_side_story_prefers_relation_types_signal(self):
        nodes = {
            "100": AnimeNode(
                "100",
                "TV Root",
                "mal",
                "tv",
                "img",
                date(2011, 1, 1),
                [
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "300", "other"),
                    AnimeRelation("100", "300", "side_story"),
                ],
            ),
            "101": AnimeNode(
                "101",
                "TV S2",
                "mal",
                "tv",
                "img",
                date(2012, 1, 1),
                [AnimeRelation("101", "100", "prequel")],
            ),
            "300": AnimeNode(
                "300",
                "Ambiguous OVA",
                "mal",
                "ova",
                "img",
                date(2012, 2, 1),
                [],
            ),
        }
        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(nodes))

        payload = service.build("100")
        sections = {section["key"]: section for section in payload.sections}

        self.assertEqual(
            [entry["media_id"] for entry in sections["specials"]["entries"]],
            ["300"],
        )
        if "ignored" in sections:
            self.assertNotIn("300", [entry["media_id"] for entry in sections["ignored"]["entries"]])

    @patch("app.services.anime_franchise.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise.AnimeFranchiseSnapshotService")
    def test_service_build_calls_snapshot_then_pipeline(
        self,
        mock_snapshot_service_cls,
        mock_pipeline_cls,
    ):
        snapshot = object()
        snapshot_instance = mock_snapshot_service_cls.return_value
        pipeline_instance = mock_pipeline_cls.return_value
        snapshot_instance.build.return_value = snapshot
        pipeline_instance.run.return_value = {"ok": True}

        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(self.nodes))
        result = service.build("101", refresh_cache=True)

        self.assertEqual(result, {"ok": True})
        snapshot_instance.build.assert_called_once_with("101", refresh_cache=True)
        pipeline_instance.run.assert_called_once_with(snapshot)

    @patch("app.services.anime_franchise.AnimeFranchiseUiPipeline")
    def test_service_facade_uses_ui_pipeline(self, mock_pipeline_cls):
        pipeline_instance = mock_pipeline_cls.return_value
        pipeline_instance.run.return_value = "payload"

        service = AnimeFranchiseService(graph_builder=FakeGraphBuilder(self.nodes))
        result = service.build("101")

        self.assertEqual(result, "payload")
        pipeline_instance.run.assert_called_once()
