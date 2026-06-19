# ruff: noqa: D101, D102

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from app.services.anime_franchise_cache import FranchisePayloadLookup
from app.services.anime_series_list import (
    AnimeSeriesBranchClassifier,
    AnimeSeriesListService,
)


class AnimeSeriesBranchClassifierTests(SimpleTestCase):
    def setUp(self):
        self.classifier = AnimeSeriesBranchClassifier()

    def test_only_alternative_and_spin_off_relations_separate(self):
        expected_kinds = {
            "alternative_version": "alternative_branch",
            "alternative_setting": "alternative_branch",
            "spin_off": "spin_off_branch",
        }
        for relation_type, expected_kind in expected_kinds.items():
            with self.subTest(relation_type=relation_type):
                decision = self.classifier.classify(
                    section_key="related_series",
                    relation_type=relation_type,
                )
                self.assertTrue(decision.separate)
                self.assertEqual(decision.group_kind, expected_kind)

    def test_parent_affiliated_relations_never_separate(self):
        for relation_type in (
            "prequel",
            "sequel",
            "full_story",
            "summary",
            "special",
            "ova",
            "tv_special",
            "side_story",
        ):
            with self.subTest(relation_type=relation_type):
                decision = self.classifier.classify(
                    section_key="related_series",
                    relation_type=relation_type,
                )
                self.assertFalse(decision.separate)
                self.assertEqual(decision.group_kind, "main_continuity")

    def test_unknown_without_parent_uses_singleton_fallback(self):
        decision = self.classifier.classify(
            section_key="unknown",
            relation_type="unknown",
            parent_known=False,
        )

        self.assertTrue(decision.separate)
        self.assertEqual(decision.group_kind, "singleton")


class AnimeSeriesListServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = AnimeSeriesListService()
        self.user = SimpleNamespace(id=1)

    def anime(self, media_id, title, *, score=None):
        return SimpleNamespace(
            item=SimpleNamespace(
                media_id=str(media_id),
                title=title,
                image=f"https://example.com/{media_id}.jpg",
            ),
            status="Planning",
            score=score,
            progress=0,
            max_progress=None,
            start_date=None,
            end_date=None,
        )

    def lookup(self, media_id, payload=None, *, alias_hit=False):
        return FranchisePayloadLookup(
            requested_media_id=str(media_id),
            canonical_media_id=str(
                payload.get("canonical_root_media_id", media_id)
                if payload
                else media_id
            ),
            payload=payload,
            meta={"truncated": False},
            alias_hit=alias_hit,
        )

    def payload(self, root_id, title, *, series=None, sections=None):
        return {
            "root_media_id": str(root_id),
            "canonical_root_media_id": str(root_id),
            "display_title": title,
            "series": {
                "key": "series",
                "title": "Series",
                "entries": series or [],
            },
            "sections": sections or [],
        }

    def entry(self, media_id, title, relation_type="", anime_media_type="movie"):
        return {
            "media_id": str(media_id),
            "source": "mal",
            "media_type": "anime",
            "anime_media_type": anime_media_type,
            "title": title,
            "relation_type": relation_type,
        }

    def build_groups(self, anime_list, lookups, *, state_roots=None, sort="title"):
        with (
            patch.object(
                AnimeSeriesListService,
                "_load_state_roots",
                return_value=state_roots or {},
            ),
            patch(
                "app.services.anime_series_list."
                "anime_franchise_cache.load_payload_for_media",
                side_effect=lambda media_id, **_kwargs: lookups[str(media_id)],
            ),
        ):
            return self.service.build_groups(
                target_user=self.user,
                anime_queryset=anime_list,
                sort_filter=sort,
            )

    def test_singleton_has_no_subtitle(self):
        anime = self.anime("1", "Standalone")

        groups = self.build_groups([anime], {"1": self.lookup("1")})

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_kind, "singleton")
        self.assertEqual(groups[0].subtitle, "")

    def test_isolated_side_story_stays_in_parent(self):
        parent = self.anime("10", "Parent")
        side_story = self.anime("11", "OVA")
        parent_payload = self.payload(
            "10",
            "Parent",
            series=[self.entry("10", "Parent", anime_media_type="tv")],
            sections=[
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [self.entry("11", "OVA", "side_story")],
                },
            ],
        )

        groups = self.build_groups(
            [parent, side_story],
            {
                "10": self.lookup("10", parent_payload),
                "11": self.lookup("11"),
            },
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "10")
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"10", "11"},
        )

    def test_side_story_local_continuity_collapses_into_parent(self):
        parent = self.anime("20", "Overlord")
        chibi_1 = self.anime("21", "Ple Ple Pleiades")
        chibi_2 = self.anime("22", "Ple Ple Pleiades 2")
        parent_payload = self.payload(
            "20",
            "Overlord",
            series=[self.entry("20", "Overlord", anime_media_type="tv")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("21", "Ple Ple Pleiades", "side_story"),
                    ],
                },
            ],
        )
        chibi_payload = self.payload(
            "21",
            "Ple Ple Pleiades",
            series=[self.entry("21", "Ple Ple Pleiades")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("22", "Ple Ple Pleiades 2", "sequel"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, chibi_1, chibi_2],
            {
                "20": self.lookup("20", parent_payload),
                "21": self.lookup("21", chibi_payload),
                "22": self.lookup("22"),
            },
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "20")
        self.assertEqual(groups[0].group_kind, "main_continuity")
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"20", "21", "22"},
        )

    def test_side_story_navigation_payload_does_not_create_affiliation_loop(self):
        parent = self.anime("25", "Parent")
        side_story = self.anime("26", "Side Story")
        parent_payload = self.payload(
            "25",
            "Parent",
            series=[self.entry("25", "Parent")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("26", "Side Story", "side_story"),
                    ],
                },
            ],
        )
        navigation_payload = self.payload(
            "26",
            "Side Story",
            series=[self.entry("26", "Side Story")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("25", "Parent", "full_story"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, side_story],
            {
                "25": self.lookup("25", parent_payload),
                "26": self.lookup("26", navigation_payload),
            },
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "25")
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"25", "26"},
        )

    def test_alternative_local_continuity_keeps_parent_context(self):
        parent = self.anime("30", "Sword Art Online")
        alternative_1 = self.anime("31", "SAO Progressive")
        alternative_2 = self.anime("32", "SAO Progressive 2")
        parent_payload = self.payload(
            "30",
            "Sword Art Online",
            series=[self.entry("30", "Sword Art Online", anime_media_type="tv")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        self.entry(
                            "31",
                            "SAO Progressive",
                            "alternative_version",
                        ),
                    ],
                },
            ],
        )
        alternative_payload = self.payload(
            "31",
            "SAO Progressive",
            series=[self.entry("31", "SAO Progressive")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("32", "SAO Progressive 2", "sequel"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, alternative_1, alternative_2],
            {
                "30": self.lookup("30", parent_payload),
                "31": self.lookup("31", alternative_payload),
                "32": self.lookup("32"),
            },
        )
        groups_by_key = {group.group_key: group for group in groups}

        self.assertEqual(
            {entry.media_id for entry in groups_by_key["31"].entries},
            {"31", "32"},
        )
        self.assertEqual(groups_by_key["31"].group_kind, "alternative_branch")
        self.assertEqual(
            groups_by_key["31"].subtitle,
            "Alternative continuity · Sword Art Online",
        )
        self.assertEqual(groups_by_key["30"].subtitle, "")

    def test_spin_off_local_continuity_keeps_parent_context(self):
        parent = self.anime("40", "A Certain Magical Index")
        spin_off_1 = self.anime("41", "A Certain Scientific Railgun")
        spin_off_2 = self.anime("42", "A Certain Scientific Railgun S")
        parent_payload = self.payload(
            "40",
            "A Certain Magical Index",
            series=[self.entry("40", "A Certain Magical Index")],
            sections=[
                {
                    "key": "spin_offs",
                    "title": "Spin Offs",
                    "entries": [
                        self.entry(
                            "41",
                            "A Certain Scientific Railgun",
                            "spin_off",
                            anime_media_type="tv",
                        ),
                    ],
                },
            ],
        )
        spin_off_payload = self.payload(
            "41",
            "A Certain Scientific Railgun",
            series=[self.entry("41", "A Certain Scientific Railgun")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("42", "A Certain Scientific Railgun S", "sequel"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, spin_off_1, spin_off_2],
            {
                "40": self.lookup("40", parent_payload),
                "41": self.lookup("41", spin_off_payload),
                "42": self.lookup("42"),
            },
        )
        groups_by_key = {group.group_key: group for group in groups}

        self.assertEqual(
            {entry.media_id for entry in groups_by_key["41"].entries},
            {"41", "42"},
        )
        self.assertEqual(groups_by_key["41"].group_kind, "spin_off_branch")
        self.assertEqual(
            groups_by_key["41"].subtitle,
            "Spin-off continuity · A Certain Magical Index",
        )

    def test_return_relation_does_not_reclassify_parent(self):
        parent = self.anime("50", "Main adaptation")
        alternative = self.anime("51", "Alternative adaptation")
        parent_payload = self.payload(
            "50",
            "Main adaptation",
            series=[self.entry("50", "Main adaptation")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        self.entry(
                            "51",
                            "Alternative adaptation",
                            "alternative_version",
                        ),
                    ],
                },
            ],
        )
        alternative_payload = self.payload(
            "51",
            "Alternative adaptation",
            series=[self.entry("51", "Alternative adaptation")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        self.entry("50", "Main adaptation", "alternative_version"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, alternative],
            {
                "50": self.lookup("50", parent_payload),
                "51": self.lookup("51", alternative_payload),
            },
        )
        groups_by_key = {group.group_key: group for group in groups}

        self.assertEqual(groups_by_key["50"].group_kind, "main_continuity")
        self.assertEqual(groups_by_key["50"].subtitle, "")

    def test_state_root_remains_cache_cold_group_key_fallback(self):
        anime = self.anime("60", "Cache-cold sequel")

        groups = self.build_groups(
            [anime],
            {"60": self.lookup("60")},
            state_roots={"60": "59"},
        )

        self.assertEqual(groups[0].group_key, "59")
        self.assertEqual(groups[0].subtitle, "")

    def test_card_score_comes_from_representative_user_score(self):
        anime = self.anime("70", "Scored anime", score=4)

        groups = self.build_groups([anime], {"70": self.lookup("70")})

        self.assertEqual(groups[0].user_score, 4)
        self.assertEqual(groups[0].best_score, 4)
