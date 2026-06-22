# ruff: noqa: D101,D102,I001

from django.test import SimpleTestCase

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder

class AnimeFranchiseGraphAlternativeTitleTests(SimpleTestCase):
    def test_node_carries_alternative_title_from_metadata(self):
        metadata = {
            "media_id": "100",
            "title": "Dungeon Meshi",
            "alternative_title_en": "Delicious in Dungeon",
            "source": "mal",
            "image": "img",
            "details": {"raw_media_type": "tv", "start_date": "2024-01-01"},
            "related": {"related_anime": []},
        }

        graph = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda _id: metadata
        ).build("100")

        self.assertEqual(graph["100"].alternative_title_en, "Delicious in Dungeon")

    def test_node_defaults_to_empty_alternative_title_when_absent(self):
        metadata = {
            "media_id": "100",
            "title": "Dungeon Meshi",
            "source": "mal",
            "image": "img",
            "details": {"raw_media_type": "tv", "start_date": "2024-01-01"},
            "related": {"related_anime": []},
        }

        graph = AnimeFranchiseGraphBuilder(
            metadata_fetcher=lambda _id: metadata
        ).build("100")

        self.assertEqual(graph["100"].alternative_title_en, "")
