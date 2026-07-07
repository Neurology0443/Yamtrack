# ruff: noqa: D101,D102
from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class DetailMediaCardSourceTests(SimpleTestCase):
    def test_media_card_detail_layout_uses_dedicated_classes(self):
        source = (ROOT / "templates/app/components/media_card.html").read_text()

        self.assertIn("detail_card_layout", source)
        self.assertIn("media-card-detail-image", source)
        self.assertIn("media-card-detail-title", source)
        self.assertIn("media-card-detail-title-link", source)
        self.assertIn("media-card-detail-progress", source)
        self.assertIn("line-clamp-1", source)
        self.assertIn("h-48", source)
        self.assertIn("from_grid", source)
        self.assertIn("aspect-2/3", source)
        self.assertIn("{% if not detail_card_layout %}", source)
        self.assertIn(
            'class="media-card-detail-title-link">{{ title }}</a>',
            source,
        )
        detail_link_classes = (
            'class="media-card-detail-title-link hover:text-indigo-400 '
            'transition duration-300"'
        )
        standard_link_classes = (
            'class="text-sm font-semibold text-white hover:text-indigo-400 '
            'transition duration-300 line-clamp-1"'
        )
        self.assertNotIn(detail_link_classes, source)
        self.assertIn(standard_link_classes, source)
        self.assertIn('title="{{ title }}">{{ title }}</a>', source)

    def assert_detail_card_css_rules(self, source):
        for expected in (
            ".media-card-detail-image",
            ".media-card-detail-title",
            ".media-card-detail-title-link",
            ".media-card-detail-progress",
            "height: 14rem",
            "object-fit: cover",
            "height: 6rem",
            "min-height: 6rem",
            "padding: 0.35rem 0.6rem 0.6rem",
            "display: flex",
            "align-items: center",
            "justify-content: center",
            "background: rgb(42, 47, 53)",
            "border-top: 1px solid rgba(255, 255, 255, 0.06)",
            "font-size: 0.80rem",
            "line-height: 1.05rem",
            "font-weight: 660",
            "transition-property: color",
            "transition-duration: 300ms",
            ".media-card-detail-title-link:hover",
            "color: var(--color-indigo-400)",
            "-webkit-line-clamp: 4",
            "bottom: 0",
            "z-index: 2",
        ):
            self.assertIn(expected, source)

    def test_detail_card_source_css_defines_console_layout_properties(self):
        source = (ROOT / "static/css/input.css").read_text()

        self.assert_detail_card_css_rules(source)

    def test_detail_card_served_css_defines_console_layout_properties(self):
        source = (ROOT / "static/css/main.css").read_text()

        self.assert_detail_card_css_rules(source)

    def test_media_details_uses_detail_layout_and_firstof_fallbacks(self):
        source = (ROOT / "templates/app/media_details.html").read_text()

        self.assertIn("detail_card_layout=True", source)
        franchise_firstof = (
            "{% firstof result.item.alternative_title_en "
            "result.item.title as display_title %}"
        )
        related_firstof = (
            "{% firstof result.item.alternative_title_en "
            "result.item.season_title result.item.title as display_title %}"
        )
        self.assertIn(franchise_firstof, source)
        self.assertIn(related_firstof, source)
        self.assertIn("title=display_title", source)
        self.assertIn("media_type == MediaTypes.ANIME.value", source)
        self.assertIn("{% elif media_type == MediaTypes.MOVIE.value %}", source)
        self.assertIn(
            '{% include "app/components/media_card.html" with '
            "item=result.item title=display_title media=result.media "
            "active=media.media_id|str_equals:result.item.media_id %}",
            source,
        )
        self.assertIn(
            '{% include "app/components/media_card.html" with '
            "item=result.item title=display_title media=result.media %}",
            source,
        )
        media_title_firstof = (
            "{% firstof media.alternative_title_en "
            "media.title as media_display_title %}"
        )
        self.assertIn(media_title_firstof, source)
        self.assertIn("{{ media_display_title }}", source)
        self.assertIn("media-detail-original-title", source)
        self.assertIn(
            "media.alternative_title_en and media.alternative_title_en != media.title",
            source,
        )

    def test_media_detail_h1_prefers_alternative_title_with_original_subtitle(self):
        template = Template(
            "{% firstof media.alternative_title_en "
            "media.title as media_display_title %}"
            "<h1>{{ media_display_title }}</h1>"
            "{% if media.alternative_title_en "
            "and media.alternative_title_en != media.title %}"
            '<p class="media-detail-original-title">{{ media.title }}</p>'
            "{% endif %}"
        )

        cases = (
            (
                {"alternative_title_en": "English Title", "title": "Original Title"},
                "<h1>English Title</h1>",
                '<p class="media-detail-original-title">Original Title</p>',
            ),
            (
                {"alternative_title_en": "", "title": "Original Title"},
                "<h1>Original Title</h1>",
                "media-detail-original-title",
            ),
            (
                {"alternative_title_en": "Original Title", "title": "Original Title"},
                "<h1>Original Title</h1>",
                "media-detail-original-title",
            ),
        )
        for media, expected, unexpected_or_expected in cases:
            with self.subTest(media=media):
                rendered = template.render(Context({"media": media}))

                self.assertIn(expected, rendered)
                if media["alternative_title_en"] == "English Title":
                    self.assertIn(unexpected_or_expected, rendered)
                else:
                    self.assertNotIn(unexpected_or_expected, rendered)

    def test_related_title_firstof_falls_back_when_season_title_is_absent(self):
        template = Template(
            "{% firstof result.item.alternative_title_en "
            "result.item.season_title result.item.title "
            "as display_title %}{{ display_title }}"
        )
        rendered = template.render(
            Context(
                {
                    "result": {
                        "item": {
                            "media_id": 16099,
                            "source": "mal",
                            "title": "Sword Art Online: Sword Art Offline",
                            "alternative_title_en": "",
                            "media_type": "anime",
                            "relation_type": "other",
                            "image": "https://example.com/image.jpg",
                        }
                    }
                }
            )
        )

        self.assertEqual(rendered, "Sword Art Online: Sword Art Offline")
