# ruff: noqa: D101,D102
from django.test import SimpleTestCase

from app.anime_franchise_footer import enrich_franchise_entries_for_footer


class AnimeFranchiseFooterTests(SimpleTestCase):
    def test_relation_tooltip_for_active_badge(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 100,
            }
        ]
        media_metadata = {
            "title": "Season 1",
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "sequel"},
                ]
            }
        }

        enriched = enrich_franchise_entries_for_footer(
            entries,
            media_metadata,
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertEqual(enriched[0]["footer_relation_value"], "sequel")
        self.assertEqual(enriched[0]["footer_relation_label"], "Sequel")
        self.assertTrue(enriched[0]["footer_relation_active"])
        self.assertEqual(enriched[0]["footer_relation_tooltip"], "Sequel to: Season 1")

    def test_relation_tooltip_for_inactive_badge(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 100,
            }
        ]

        enriched = enrich_franchise_entries_for_footer(
            entries,
            {},
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertFalse(enriched[0]["footer_relation_active"])
        self.assertEqual(enriched[0]["footer_relation_tooltip"], "Sequel to: Season 1")

    def test_relation_tooltip_is_empty_without_resolved_source(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 999,
            }
        ]

        enriched = enrich_franchise_entries_for_footer(
            entries,
            {},
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertEqual(enriched[0]["footer_relation_tooltip"], "")

    def test_relation_tooltip_is_empty_for_unknown_relation(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "unknown_relation",
                "linked_series_line_media_id": 100,
            }
        ]

        enriched = enrich_franchise_entries_for_footer(
            entries,
            {},
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertEqual(enriched[0]["footer_relation_tooltip"], "")

    def test_relation_tooltip_for_active_badge_prefers_season_title(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 100,
            }
        ]
        media_metadata = {
            "title": "Generic Anime Title",
            "season_title": "Season 4",
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "prequel"},
                ]
            },
        }

        enriched = enrich_franchise_entries_for_footer(
            entries,
            media_metadata,
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertEqual(
            enriched[0]["footer_relation_tooltip"],
            "Prequel to: Season 4",
        )

    def test_relation_tooltip_for_active_badge_uses_current_page_title(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 100,
            }
        ]
        media_metadata = {
            "title": "Current Page Season 4",
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "prequel"},
                ]
            },
        }

        enriched = enrich_franchise_entries_for_footer(
            entries,
            media_metadata,
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertEqual(enriched[0]["footer_relation_value"], "prequel")
        self.assertTrue(enriched[0]["footer_relation_active"])
        self.assertEqual(
            enriched[0]["footer_relation_tooltip"],
            "Prequel to: Current Page Season 4",
        )

    def test_relation_tooltip_for_active_badge_is_empty_without_current_title(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 100,
            }
        ]
        media_metadata = {
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "sequel"},
                ]
            },
        }

        enriched = enrich_franchise_entries_for_footer(
            entries,
            media_metadata,
            series_entries=[{"media_id": 100, "title": "Season 1"}],
        )

        self.assertTrue(enriched[0]["footer_relation_active"])
        self.assertEqual(enriched[0]["footer_relation_tooltip"], "")

    def test_relation_tooltip_prefers_series_label(self):
        entries = [
            {
                "media_id": 200,
                "title": "OVA",
                "relation_type": "side_story",
                "linked_series_line_media_id": 100,
            }
        ]
        series_entries = [
            {
                "media_id": 100,
                "title": "Dungeon ni Deai wo Motomeru no wa Machigatteiru Darou ka",
                "series_label": "Season 1",
            }
        ]

        enriched = enrich_franchise_entries_for_footer(
            entries,
            {},
            series_entries=series_entries,
        )

        self.assertEqual(
            enriched[0]["footer_relation_tooltip"],
            "Side story from: Season 1",
        )

    def test_relation_tooltip_follows_displayed_relation(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
                "linked_series_line_media_id": 400,
            }
        ]
        media_metadata = {
            "title": "Current Season 4",
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "prequel"},
                ]
            },
        }

        enriched = enrich_franchise_entries_for_footer(
            entries,
            media_metadata,
            series_entries=[{"media_id": 400, "title": "Season 4"}],
        )

        self.assertEqual(enriched[0]["footer_relation_value"], "prequel")
        self.assertEqual(
            enriched[0]["footer_relation_tooltip"],
            "Prequel to: Current Season 4",
        )
