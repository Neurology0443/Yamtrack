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

    def assert_separate(self, relation_type, **signals):
        decision = self.classifier.classify(
            section_key="related_series",
            relation_type=relation_type,
            **signals,
        )
        self.assertTrue(decision.separate)

    def assert_parent(self, relation_type, section_key="related_series"):
        decision = self.classifier.classify(
            section_key=section_key,
            relation_type=relation_type,
        )
        self.assertFalse(decision.separate)

    def test_alternative_version_is_separate(self):
        self.assert_separate("alternative_version")

    def test_alternative_setting_is_separate(self):
        self.assert_separate("alternative_setting")

    def test_spin_off_is_separate(self):
        self.assert_separate("spin_off")

    def test_isolated_side_story_stays_with_parent(self):
        self.assert_parent("side_story")

    def test_side_story_with_followed_sequel_is_separate(self):
        self.assert_separate(
            "side_story",
            has_followed_local_prequel_or_sequel=True,
        )

    def test_side_story_with_followed_prequel_is_separate(self):
        self.assert_separate(
            "side_story",
            has_followed_local_prequel_or_sequel=True,
        )

    def test_side_story_with_meaningful_local_payload_is_separate(self):
        self.assert_separate(
            "side_story",
            has_meaningful_local_branch_payload=True,
        )

    def test_side_story_with_multiple_followed_local_entries_is_separate(self):
        self.assert_separate(
            "side_story",
            followed_local_branch_size=2,
        )

    def test_parent_relations_and_sections_remain_with_parent(self):
        for relation_type in ("prequel", "sequel", "full_story", "summary"):
            with self.subTest(relation_type=relation_type):
                self.assert_parent(relation_type)
        for section_key in ("specials", "ova", "ovas", "tv_specials"):
            with self.subTest(section_key=section_key):
                self.assert_parent("", section_key=section_key)

    def test_unknown_relation_uses_conservative_parent_fallback(self):
        self.assert_parent("unknown_relation")


class AnimeSeriesListServiceTests(SimpleTestCase):
    def setUp(self):
        self.service = AnimeSeriesListService()
        self.user = SimpleNamespace(id=1)

    def anime(self, media_id, title):
        return SimpleNamespace(
            item=SimpleNamespace(
                media_id=str(media_id),
                title=title,
                image=f"https://example.com/{media_id}.jpg",
            ),
            status="Planning",
            score=None,
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

    @patch.object(AnimeSeriesListService, "_load_state_roots", return_value={})
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_sao_branches_are_grouped_deterministically(
        self,
        load_payload,
        _load_state_roots,
    ):
        sao = self.anime("1", "Sword Art Online")
        progressive_1 = self.anime("2", "Sword Art Online Progressive")
        progressive_2 = self.anime("3", "Sword Art Online Progressive 2")
        gun_gale = self.anime("4", "Sword Art Online Alternative: Gun Gale Online")
        parent_payload = self.payload(
            "1",
            "Sword Art Online",
            series=[self.entry("1", "Sword Art Online", anime_media_type="tv")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        self.entry(
                            "2",
                            "Sword Art Online Progressive",
                            "alternative_version",
                        ),
                    ],
                },
                {
                    "key": "spin_offs",
                    "title": "Spin Offs",
                    "entries": [
                        self.entry(
                            "4",
                            "Sword Art Online Alternative: Gun Gale Online",
                            "spin_off",
                            anime_media_type="tv",
                        ),
                    ],
                },
            ],
        )
        progressive_payload = self.payload(
            "2",
            "Sword Art Online Progressive",
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry(
                            "3",
                            "Sword Art Online Progressive 2",
                            "sequel",
                        ),
                    ],
                },
            ],
        )
        lookups = {
            "1": self.lookup("1", parent_payload),
            "2": self.lookup("2", progressive_payload),
            "3": self.lookup("3"),
            "4": self.lookup("4"),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[sao, progressive_1, progressive_2, gun_gale],
            sort_filter="title",
        )

        self.assertEqual([group.group_key for group in groups], ["1", "4", "2"])
        entries_by_group = {
            group.group_key: {entry.media_id for entry in group.entries}
            for group in groups
        }
        self.assertEqual(entries_by_group["1"], {"1"})
        self.assertEqual(entries_by_group["2"], {"2", "3"})
        self.assertEqual(entries_by_group["4"], {"4"})
        self.assertTrue(
            all(call.kwargs == {"touch": False} for call in load_payload.mock_calls)
        )

    @patch.object(AnimeSeriesListService, "_load_state_roots", return_value={})
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_isolated_side_story_stays_in_parent(
        self,
        load_payload,
        _load_state_roots,
    ):
        parent = self.anime("10", "Re:Zero")
        side_story = self.anime("11", "Memory Snow")
        payload = self.payload(
            "10",
            "Re:Zero",
            series=[self.entry("10", "Re:Zero", anime_media_type="tv")],
            sections=[
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        self.entry("11", "Memory Snow", "side_story"),
                    ],
                },
            ],
        )
        lookups = {
            "10": self.lookup("10", payload),
            "11": self.lookup("11"),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[parent, side_story],
            sort_filter="title",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"10", "11"},
        )

    @patch.object(AnimeSeriesListService, "_load_state_roots", return_value={})
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_side_story_with_direct_followed_sequel_is_separate(
        self,
        load_payload,
        _load_state_roots,
    ):
        parent = self.anime("20", "Parent")
        side_story = self.anime("21", "Side Story")
        sequel = self.anime("22", "Side Story 2")
        parent_payload = self.payload(
            "20",
            "Parent",
            series=[self.entry("20", "Parent", anime_media_type="tv")],
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry(
                            "21",
                            "Side Story",
                            "side_story",
                            anime_media_type="tv",
                        ),
                    ],
                },
            ],
        )
        branch_payload = self.payload(
            "21",
            "Side Story",
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry("22", "Side Story 2", "sequel"),
                    ],
                },
            ],
        )
        lookups = {
            "20": self.lookup("20", parent_payload),
            "21": self.lookup("21", branch_payload),
            "22": self.lookup("22"),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[parent, side_story, sequel],
            sort_filter="title",
        )

        entries_by_group = {
            group.group_key: {entry.media_id for entry in group.entries}
            for group in groups
        }
        self.assertEqual(entries_by_group["20"], {"20"})
        self.assertEqual(entries_by_group["21"], {"21", "22"})

    @patch.object(AnimeSeriesListService, "_load_state_roots", return_value={})
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_side_story_with_navigation_payload_stays_in_parent(
        self,
        load_payload,
        _load_state_roots,
    ):
        parent = self.anime("30", "Parent Series")
        side_story = self.anime("31", "Isolated OVA")
        parent_payload = self.payload(
            "30",
            "Parent Series",
            series=[self.entry("30", "Parent Series", anime_media_type="tv")],
            sections=[
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        self.entry("31", "Isolated OVA", "side_story"),
                    ],
                },
            ],
        )
        navigation_payload = self.payload(
            "31",
            "Isolated OVA",
            sections=[
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        self.entry(
                            "30",
                            "Parent Series",
                            "full_story",
                            anime_media_type="tv",
                        ),
                    ],
                },
            ],
        )
        lookups = {
            "30": self.lookup("30", parent_payload),
            "31": self.lookup("31", navigation_payload),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[parent, side_story],
            sort_filter="title",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "30")
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"30", "31"},
        )

    @patch.object(AnimeSeriesListService, "_load_state_roots", return_value={})
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_alternative_return_link_does_not_reclassify_parent(
        self,
        load_payload,
        _load_state_roots,
    ):
        parent = self.anime("40", "Sword Art Online")
        progressive = self.anime("41", "Sword Art Online Progressive")
        parent_payload = self.payload(
            "40",
            "Sword Art Online",
            series=[self.entry("40", "Sword Art Online", anime_media_type="tv")],
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternative Versions",
                    "entries": [
                        self.entry(
                            "41",
                            "Sword Art Online Progressive",
                            "alternative_version",
                        ),
                    ],
                },
            ],
        )
        progressive_payload = self.payload(
            "41",
            "Sword Art Online Progressive",
            sections=[
                {
                    "key": "alternatives",
                    "title": "Alternative Versions",
                    "entries": [
                        self.entry(
                            "40",
                            "Sword Art Online",
                            "alternative_version",
                            anime_media_type="tv",
                        ),
                    ],
                },
            ],
        )
        lookups = {
            "40": self.lookup("40", parent_payload),
            "41": self.lookup("41", progressive_payload),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[parent, progressive],
            sort_filter="title",
        )

        groups_by_key = {group.group_key: group for group in groups}
        self.assertEqual(groups_by_key["40"].group_kind, "main_continuity")
        self.assertEqual(groups_by_key["41"].group_kind, "alternative_branch")

    @patch.object(
        AnimeSeriesListService,
        "_load_state_roots",
        return_value={"50": "50", "51": "50"},
    )
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_shared_import_component_does_not_separate_isolated_side_story(
        self,
        load_payload,
        _load_state_roots,
    ):
        parent = self.anime("50", "Parent Series")
        side_story = self.anime("51", "Isolated OVA")
        parent_payload = self.payload(
            "50",
            "Parent Series",
            series=[self.entry("50", "Parent Series", anime_media_type="tv")],
            sections=[
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        self.entry("51", "Isolated OVA", "side_story"),
                    ],
                },
            ],
        )
        lookups = {
            "50": self.lookup("50", parent_payload),
            "51": self.lookup("51"),
        }
        load_payload.side_effect = lambda media_id, **_kwargs: lookups[str(media_id)]

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[parent, side_story],
            sort_filter="title",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "50")
        self.assertEqual(
            {entry.media_id for entry in groups[0].entries},
            {"50", "51"},
        )

    @patch.object(
        AnimeSeriesListService,
        "_load_state_roots",
        return_value={"60": "59"},
    )
    @patch("app.services.anime_series_list.anime_franchise_cache.load_payload_for_media")
    def test_state_root_remains_group_key_fallback_without_payload(
        self,
        load_payload,
        _load_state_roots,
    ):
        orphan = self.anime("60", "Cache-cold sequel")
        load_payload.return_value = self.lookup("60")

        groups = self.service.build_groups(
            target_user=self.user,
            anime_queryset=[orphan],
            sort_filter="title",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_key, "59")
        self.assertEqual(groups[0].group_kind, "main_continuity")
