# ruff: noqa: D101,D102
from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from app.services.anime_franchise_context import (
    _build_no_series_render_continuity_entries,
    _copy_entries,
    has_displayable_franchise_entries,
    prepare_anime_franchise_context,
)


class AnimeFranchiseContextTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user_a = get_user_model().objects.create_user(
            username="user-a",
        )
        self.user_b = get_user_model().objects.create_user(
            username="user-b",
        )
        self.payload = {
            "root_media_id": "100",
            "display_title": "Root",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "100",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Root",
                        "image": "img",
                    }
                ],
            },
            "sections": [
                {
                    "key": "movies",
                    "title": "Movies",
                    "entries": [
                        {
                            "media_id": "101",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Movie",
                            "image": "img",
                        }
                    ],
                    "visible_in_ui": True,
                    "hidden_if_empty": True,
                },
            ],
        }

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def _relation(self, source_id, target_id, relation_type):
        return {
            "source_media_id": source_id,
            "target_media_id": target_id,
            "relation_type": relation_type,
        }

    def _component_entry(self, media_id, title, rank):
        return {
            "media_id": media_id,
            "title": title,
            "image": f"img-{media_id}",
            "source": "mal",
            "media_type": "anime",
            "anime_media_type": "movie",
            "start_date": None,
            "runtime_minutes": None,
            "episode_count": None,
            "section_sort_rank": rank,
        }

    def _code_geass_no_series_payload(self):
        entries = [
            self._component_entry("34438", "Koudou", 0),
            self._component_entry("34439", "Handou", 1),
            self._component_entry("34440", "Oudou", 2),
        ]
        return {
            "root_media_id": "34438",
            "display_title": "Koudou",
            "canonical_root_media_id": "34438",
            "has_series_line": False,
            "continuity_component_media_ids": ["34438", "34439", "34440"],
            "continuity_component_entries": entries,
            "continuity_component_relations": [
                self._relation("34438", "34439", "sequel"),
                self._relation("34439", "34438", "prequel"),
                self._relation("34439", "34440", "sequel"),
                self._relation("34440", "34439", "prequel"),
            ],
            "series": {"key": "series", "title": "Series", "entries": []},
            "sections": [
                {
                    "key": "continuity_extras",
                    "title": "Main Story Extras",
                    "entries": [entries[1], entries[2]],
                    "visible_in_ui": True,
                    "hidden_if_empty": True,
                }
            ],
        }

    def _overlord_no_series_payload(self):
        ids = ["31138", "33372", "37087", "37781", "48897"]
        titles = [
            "Ple Ple Pleiades",
            "Nazarick Saidai no Kiki",
            "Ple Ple Pleiades 2",
            "Ple Ple Pleiades 3",
            "Ple Ple Pleiades 4",
        ]
        entries = [
            self._component_entry(media_id, title, rank)
            for rank, (media_id, title) in enumerate(zip(ids, titles, strict=True))
        ]
        return {
            "root_media_id": "31138",
            "display_title": "Ple Ple Pleiades",
            "canonical_root_media_id": "31138",
            "has_series_line": False,
            "continuity_component_media_ids": ids,
            "continuity_component_entries": entries,
            "continuity_component_relations": [
                self._relation("31138", "33372", "sequel"),
                self._relation("33372", "31138", "prequel"),
                self._relation("31138", "37087", "sequel"),
                self._relation("37087", "31138", "prequel"),
                self._relation("37087", "37781", "sequel"),
                self._relation("37781", "37087", "prequel"),
                self._relation("37781", "48897", "sequel"),
                self._relation("48897", "37781", "prequel"),
                self._relation("37781", "37675", "parent_story"),
                self._relation("48897", "48895", "other"),
            ],
            "series": {"key": "series", "title": "Series", "entries": []},
            "sections": [
                {
                    "key": "continuity_extras",
                    "title": "Main Story Extras",
                    "entries": entries[1:],
                    "visible_in_ui": True,
                    "hidden_if_empty": True,
                },
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        {
                            "media_id": "35073",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Overlord II",
                            "relation_type": "parent_story",
                        }
                    ],
                },
            ],
        }


    def test_copy_entries_ignores_non_dict_values(self):
        self.assertEqual(_copy_entries([{"a": 1}, "bad", None]), [{"a": 1}])
        self.assertEqual(_copy_entries({"not": "a-list"}), [])

    def test_has_displayable_franchise_entries(self):
        self.assertFalse(has_displayable_franchise_entries(None))
        self.assertFalse(
            has_displayable_franchise_entries({"series": {}, "sections": []}),
        )
        self.assertTrue(
            has_displayable_franchise_entries(
                {"series": {"entries": [object()]}, "sections": []},
            )
        )
        self.assertTrue(
            has_displayable_franchise_entries(
                {"series": {"entries": []}, "sections": [{"entries": [object()]}]},
            )
        )
        self.assertTrue(
            has_displayable_franchise_entries(
                {
                    "has_series_line": False,
                    "series": {"entries": []},
                    "sections": [],
                    "continuity_component_entries": [
                        {"media_id": "1"},
                        {"media_id": "2"},
                    ],
                },
            )
        )
        self.assertFalse(
            has_displayable_franchise_entries(
                {
                    "has_series_line": True,
                    "series": {"entries": []},
                    "sections": [],
                    "continuity_component_entries": [
                        {"media_id": "1"},
                        {"media_id": "2"},
                    ],
                },
            )
        )

    def test_no_series_render_helper_includes_canonical_root_for_alias_page(self):
        entries = _build_no_series_render_continuity_entries(
            self._code_geass_no_series_payload(),
            "34439",
        )

        media_ids = [entry["media_id"] for entry in entries]
        self.assertEqual(media_ids, ["34438", "34440"])

    def test_no_series_render_helper_excludes_canonical_root_page(self):
        entries = _build_no_series_render_continuity_entries(
            self._code_geass_no_series_payload(),
            "34438",
        )

        media_ids = [entry["media_id"] for entry in entries]
        self.assertEqual(media_ids, ["34439", "34440"])

    def test_no_series_render_helper_overlord_includes_root_not_in_section(self):
        entries = _build_no_series_render_continuity_entries(
            self._overlord_no_series_payload(),
            "33372",
        )

        media_ids = [entry["media_id"] for entry in entries]
        self.assertEqual(media_ids, ["31138", "37087", "37781", "48897"])
        self.assertNotIn("33372", media_ids)

    def test_no_series_render_helper_does_not_inject_informative_relations(self):
        payload = self._overlord_no_series_payload()
        entries = _build_no_series_render_continuity_entries(payload, "33372")

        component_ids = {
            entry["media_id"] for entry in payload["continuity_component_entries"]
        }
        rendered_ids = {entry["media_id"] for entry in entries}
        self.assertFalse({"35073", "37675", "48895"} & component_ids)
        self.assertFalse({"35073", "37675", "48895"} & rendered_ids)

    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_rebuilds_no_series_continuity_extras_at_render(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: items  # noqa: ARG005

        context = prepare_anime_franchise_context(
            self._request(self.user_a),
            self._code_geass_no_series_payload(),
            {"media_id": "34439"},
        )

        entries = context["sections"][0]["entries"]
        media_ids = [entry["media_id"] for entry in entries]
        self.assertIn("34438", media_ids)
        self.assertNotIn("34439", media_ids)

    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_keeps_series_line_sections_unchanged(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        payload = deepcopy(self.payload)
        payload["has_series_line"] = True
        payload["continuity_component_entries"] = [
            self._component_entry("999", "Should Not Render", 0)
        ]
        original_sections = deepcopy(payload["sections"])
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: items  # noqa: ARG005

        context = prepare_anime_franchise_context(
            self._request(self.user_a),
            payload,
            {"media_id": "100"},
        )

        self.assertEqual(
            [entry["media_id"] for entry in context["sections"][0]["entries"]],
            [entry["media_id"] for entry in original_sections[0]["entries"]],
        )

    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_does_not_mutate_cached_payload(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        original = deepcopy(self.payload)
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: [  # noqa: ARG005
            {"item": item, "media": None} for item in items
        ]

        prepare_anime_franchise_context(self._request(self.user_a), self.payload, {})

        self.assertEqual(self.payload, original)

    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_for_two_users_does_not_share_user_data(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        original = deepcopy(self.payload)
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: [  # noqa: ARG005
            {"item": {**item, "viewer": request.user.username}, "media": None}
            for item in items
        ]

        context_a = prepare_anime_franchise_context(
            self._request(self.user_a),
            self.payload,
            {},
        )
        context_b = prepare_anime_franchise_context(
            self._request(self.user_b),
            self.payload,
            {},
        )

        self.assertEqual(self.payload, original)
        self.assertEqual(context_a["series"]["entries"][0]["item"]["viewer"], "user-a")
        self.assertEqual(context_b["series"]["entries"][0]["item"]["viewer"], "user-b")


    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_recomputes_is_current_from_media_metadata(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        payload = {
            "root_media_id": "223",
            "display_title": "Dragon Ball",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "223",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball",
                        "is_current": False,
                    },
                    {
                        "media_id": "269",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball GT",
                        "is_current": True,
                    },
                ],
            },
            "sections": [
                {
                    "key": "extras",
                    "title": "Extras",
                    "entries": [
                        {
                            "media_id": "223",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Special",
                            "is_current": False,
                        },
                    ],
                },
            ],
        }
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: [  # noqa: ARG005
            {"item": item, "media": None} for item in items
        ]

        context = prepare_anime_franchise_context(
            self._request(self.user_a),
            payload,
            {"media_id": "223"},
        )

        entries = context["series"]["entries"]
        self.assertTrue(entries[0]["item"]["is_current"])
        self.assertFalse(entries[1]["item"]["is_current"])
        section_entry = context["sections"][0]["entries"][0]
        self.assertTrue(section_entry["item"]["is_current"])

    @patch("app.services.anime_franchise_context.enrich_franchise_entries_for_footer")
    @patch("app.services.anime_franchise_context.helpers.enrich_items_with_user_data")
    def test_prepare_context_skips_malformed_sections(
        self,
        mock_enrich_items,
        mock_footer,
    ):
        payload = deepcopy(self.payload)
        payload["sections"].append({"entries": [{"media_id": "999"}]})
        mock_footer.side_effect = lambda entries, media_metadata: entries  # noqa: ARG005
        mock_enrich_items.side_effect = lambda request, items, section: [  # noqa: ARG005
            {"item": item, "media": None} for item in items
        ]

        context = prepare_anime_franchise_context(
            self._request(self.user_a),
            payload,
            {},
        )

        self.assertEqual(len(context["sections"]), 1)
