# ruff: noqa: D101, D102
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from django.template import Context, Template

from app.templatetags.app_tags import display_media_title


class DisplayMediaTitleTests(TestCase):
    def test_prefers_alternative_title_for_dict(self):
        item = {
            "title": "Original",
            "season_title": "Season",
            "alternative_title_en": "English",
        }

        self.assertEqual(display_media_title(item), "English")

    def test_falls_back_to_season_title_for_dict(self):
        item = {
            "title": "Original",
            "season_title": "Season",
            "alternative_title_en": "",
        }

        self.assertEqual(display_media_title(item), "Season")

    def test_falls_back_to_title_when_season_title_missing_for_dict(self):
        item = {
            "title": "Original",
            "alternative_title_en": "",
        }

        self.assertEqual(display_media_title(item), "Original")

    def test_returns_empty_string_for_empty_dict(self):
        self.assertEqual(display_media_title({}), "")

    def test_supports_objects(self):
        item = SimpleNamespace(
            title="Original",
            season_title="Season",
            alternative_title_en="English",
        )

        self.assertEqual(display_media_title(item), "English")

    def test_supports_object_missing_season_title(self):
        item = SimpleNamespace(
            title="Original",
            alternative_title_en="",
        )

        self.assertEqual(display_media_title(item), "Original")

    def test_template_filter_handles_missing_season_title(self):
        template = Template("{% load app_tags %}{{ item|display_media_title }}")
        rendered = template.render(
            Context(
                {
                    "item": {
                        "media_id": 16099,
                        "source": "mal",
                        "title": "Sword Art Online: Sword Art Offline",
                        "alternative_title_en": "",
                        "media_type": "anime",
                        "relation_type": "other",
                        "image": "image-url",
                    }
                }
            )
        )

        self.assertEqual(rendered, "Sword Art Online: Sword Art Offline")
