# ruff: noqa: D101,D102
from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from app.services.anime_franchise_context import (
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
