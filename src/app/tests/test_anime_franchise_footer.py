# ruff: noqa: D101,D102
from django.test import SimpleTestCase

from app.anime_franchise_footer import enrich_franchise_entries_for_footer


class AnimeFranchiseFooterTests(SimpleTestCase):
    def test_direct_relation_sets_active_footer_fields_without_tooltip(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "side_story",
                "anime_media_type": "ova",
            }
        ]
        media_metadata = {
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "sequel"},
                ]
            }
        }

        enriched = enrich_franchise_entries_for_footer(entries, media_metadata)

        self.assertEqual(enriched[0]["footer_relation_value"], "sequel")
        self.assertEqual(enriched[0]["footer_relation_label"], "Sequel")
        self.assertTrue(enriched[0]["footer_relation_active"])
        self.assertNotIn("footer_relation_tooltip", enriched[0])

    def test_inactive_relation_falls_back_to_entry_relation_without_tooltip(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "side_story",
            }
        ]

        enriched = enrich_franchise_entries_for_footer(entries, {})

        self.assertEqual(enriched[0]["footer_relation_value"], "side_story")
        self.assertEqual(enriched[0]["footer_relation_label"], "Side Story")
        self.assertFalse(enriched[0]["footer_relation_active"])
        self.assertNotIn("footer_relation_tooltip", enriched[0])

    def test_anime_media_type_sets_footer_format_label(self):
        entries = [
            {"media_id": 1, "anime_media_type": "tv"},
            {"media_id": 2, "anime_media_type": "ova"},
            {"media_id": 3, "anime_media_type": "ona"},
            {"media_id": 4, "anime_media_type": "music_video"},
        ]

        enriched = enrich_franchise_entries_for_footer(entries, {})

        self.assertEqual(enriched[0]["footer_format"], "TV")
        self.assertEqual(enriched[1]["footer_format"], "OVA")
        self.assertEqual(enriched[2]["footer_format"], "ONA")
        self.assertEqual(enriched[3]["footer_format"], "Music Video")

    def test_direct_relation_takes_priority_over_entry_relation(self):
        entries = [
            {
                "media_id": 200,
                "title": "Special",
                "relation_type": "sequel",
            }
        ]
        media_metadata = {
            "related": {
                "related_anime": [
                    {"media_id": 200, "relation_type": "prequel"},
                ]
            }
        }

        enriched = enrich_franchise_entries_for_footer(entries, media_metadata)

        self.assertEqual(enriched[0]["footer_relation_value"], "prequel")
        self.assertEqual(enriched[0]["footer_relation_label"], "Prequel")
        self.assertTrue(enriched[0]["footer_relation_active"])
