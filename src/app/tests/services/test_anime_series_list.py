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

    def test_singleton_has_no_context(self):
        anime = self.anime("1", "Standalone")

        groups = self.build_groups([anime], {"1": self.lookup("1")})

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_kind, "singleton")
        self.assertEqual(groups[0].context_label, "")
        self.assertEqual(groups[0].context_title, "")

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

    def test_parent_child_return_links_do_not_create_affiliation_loops(self):
        for index, relation_type in enumerate(
            ("side_story", "special", "ova", "summary"),
            start=1,
        ):
            with self.subTest(relation_type=relation_type):
                parent_id = str(index * 10)
                child_id = str(index * 10 + 1)
                parent = self.anime(parent_id, "Parent")
                child = self.anime(child_id, "Child")
                parent_payload = self.payload(
                    parent_id,
                    "Parent",
                    series=[self.entry(parent_id, "Parent")],
                    sections=[
                        {
                            "key": "related_series",
                            "title": "Related Series",
                            "entries": [
                                self.entry(child_id, "Child", relation_type),
                            ],
                        },
                    ],
                )
                navigation_payload = self.payload(
                    child_id,
                    "Child",
                    series=[self.entry(child_id, "Child")],
                    sections=[
                        {
                            "key": "related_series",
                            "title": "Related Series",
                            "entries": [
                                self.entry(parent_id, "Parent", "full_story"),
                            ],
                        },
                    ],
                )

                groups = self.build_groups(
                    [parent, child],
                    {
                        parent_id: self.lookup(parent_id, parent_payload),
                        child_id: self.lookup(child_id, navigation_payload),
                    },
                )

                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0].group_key, parent_id)
                self.assertEqual(
                    {entry.media_id for entry in groups[0].entries},
                    {parent_id, child_id},
                )

    def test_spice_like_alternatives_collapse_into_local_continuity(self):
        parent = self.anime("51122", "Spice and Wolf")
        old_1 = self.anime("2966", "Old adaptation")
        old_2 = self.anime("5341", "Old adaptation II")
        old_extra = self.anime("6007", "Old adaptation OVA")
        parent_payload = self.payload(
            "51122",
            "Spice and Wolf",
            series=[self.entry("51122", "Spice and Wolf")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        self.entry("2966", "Old adaptation", "alternative_version"),
                        self.entry("5341", "Old adaptation II", "alternative_version"),
                        self.entry("6007", "Old adaptation OVA", "alternative_version"),
                    ],
                },
            ],
        )
        local_payload = self.payload(
            "2966",
            "Old adaptation",
            series=[
                self.entry("2966", "Old adaptation"),
                self.entry("5341", "Old adaptation II", "sequel"),
            ],
            sections=[
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        self.entry("6007", "Old adaptation OVA", "ova"),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, old_1, old_2, old_extra],
            {
                "51122": self.lookup("51122", parent_payload),
                "2966": self.lookup("2966", local_payload),
                "5341": self.lookup("5341"),
                "6007": self.lookup("6007"),
            },
        )
        groups_by_key = {group.group_key: group for group in groups}

        self.assertEqual(
            {entry.media_id for entry in groups_by_key["2966"].entries},
            {"2966", "5341", "6007"},
        )
        self.assertEqual(
            groups_by_key["2966"].context_label,
            "Alternative version",
        )
        self.assertIn(
            "Spice and Wolf",
            groups_by_key["2966"].context_title,
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
                        self.entry(
                            "30",
                            "Sword Art Online",
                            "alternative_version",
                        ),
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
            groups_by_key["31"].context_label,
            "Alternative version",
        )
        self.assertEqual(
            groups_by_key["31"].context_title,
            "Alternative version · Sword Art Online",
        )
        self.assertEqual(groups_by_key["30"].context_label, "")

    def test_alternative_setting_uses_specific_context_label(self):
        parent = self.anime("35", "Parent")
        branch = self.anime("36", "Different setting")
        parent_payload = self.payload(
            "35",
            "Parent",
            series=[self.entry("35", "Parent")],
            sections=[
                {
                    "key": "alternative_settings",
                    "title": "Alternative Settings",
                    "entries": [
                        self.entry(
                            "36",
                            "Different setting",
                            "",
                        ),
                    ],
                },
            ],
        )

        groups = self.build_groups(
            [parent, branch],
            {
                "35": self.lookup("35", parent_payload),
                "36": self.lookup("36"),
            },
        )
        groups_by_key = {group.group_key: group for group in groups}

        self.assertEqual(
            groups_by_key["36"].context_label,
            "Alternative setting",
        )

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
            groups_by_key["41"].context_label,
            "Spin off",
        )
        self.assertEqual(
            groups_by_key["41"].context_title,
            "Spin off · A Certain Magical Index",
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
        self.assertEqual(groups_by_key["50"].context_label, "")
        self.assertEqual(
            groups_by_key["51"].context_label,
            "Alternative version",
        )

    def test_state_root_remains_cache_cold_group_key_fallback(self):
        anime = self.anime("60", "Cache-cold sequel")

        groups = self.build_groups(
            [anime],
            {"60": self.lookup("60")},
            state_roots={"60": "59"},
        )

        self.assertEqual(groups[0].group_key, "59")
        self.assertEqual(groups[0].context_label, "")

    def test_card_score_comes_from_representative_user_score(self):
        anime = self.anime("70", "Scored anime", score=4)

        groups = self.build_groups([anime], {"70": self.lookup("70")})

        self.assertEqual(groups[0].user_score, 4)
        self.assertEqual(groups[0].best_score, 4)

    def test_franchise_payload_reads_never_touch_cache(self):
        anime = self.anime("80", "Read only")
        with (
            patch.object(
                AnimeSeriesListService,
                "_load_state_roots",
                return_value={},
            ),
            patch(
                "app.services.anime_series_list."
                "anime_franchise_cache.load_payload_for_media",
                return_value=self.lookup("80"),
            ) as load_payload,
        ):
            self.service.build_groups(
                target_user=self.user,
                anime_queryset=[anime],
                sort_filter="title",
            )

        load_payload.assert_called_once_with("80", touch=False)
