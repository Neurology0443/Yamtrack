# ruff: noqa: D101,D102
from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_local_series_resolver import AnimeLocalSeriesResolver


class AnimeLocalSeriesResolverTests(SimpleTestCase):
    def setUp(self):
        self.resolver = AnimeLocalSeriesResolver()

    @staticmethod
    def _node(
        media_id,
        title=None,
        *,
        media_type="tv",
        start_date=None,
    ):
        return AnimeNode(
            media_id=str(media_id),
            title=title or f"Anime {media_id}",
            source="mal",
            media_type=media_type,
            image=f"https://example.com/{media_id}.jpg",
            start_date=start_date,
        )

    def _snapshot(
        self,
        nodes,
        relations,
        *,
        root_media_id=None,
        series_line_ids=(),
        continuity_ids=(),
    ):
        nodes_by_media_id = {node.media_id: node for node in nodes}
        root_media_id = str(root_media_id or nodes[0].media_id)
        series_line = [
            nodes_by_media_id[str(media_id)] for media_id in series_line_ids
        ]
        continuity_component = [
            nodes_by_media_id[str(media_id)] for media_id in continuity_ids
        ]
        if not continuity_component:
            continuity_component = list(nodes)
        return AnimeFranchiseSnapshot(
            root_node=nodes_by_media_id[root_media_id],
            nodes_by_media_id=nodes_by_media_id,
            all_normalized_relations=list(relations),
            continuity_component=continuity_component,
            series_line=series_line,
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=bool(series_line),
            fallback_anchor_media_id=root_media_id,
            canonical_root_media_id=(
                series_line[0].media_id if series_line else root_media_id
            ),
        )

    def test_alternative_version_separates_local_branch(self):
        nodes = [
            self._node("223", "Dragon Ball", start_date=date(1986, 2, 26)),
            self._node("502", "Dragon Ball Movie 1", media_type="movie"),
            self._node("891", "Dragon Ball Movie 2", media_type="movie"),
            self._node("892", "Dragon Ball Movie 3", media_type="movie"),
            self._node("893", "Dragon Ball Movie 4", media_type="movie"),
        ]
        relations = [
            AnimeRelation("223", "502", "alternative_version"),
            AnimeRelation("502", "891", "sequel"),
            AnimeRelation("891", "892", "sequel"),
            AnimeRelation("892", "893", "sequel"),
        ]
        snapshot = self._snapshot(
            nodes,
            relations,
            root_media_id="223",
            series_line_ids=("223",),
        )

        resolution = self.resolver.resolve(
            snapshot,
            {"223", "502", "891", "892", "893"},
        )

        self.assertEqual(
            [
                (
                    group.root_media_id,
                    group.group_kind,
                    group.member_media_ids,
                    group.context_parent_media_id,
                    group.context_relation_type,
                )
                for group in resolution.groups
            ],
            [
                ("223", "singleton", ["223"], None, None),
                (
                    "502",
                    "alternative_branch",
                    ["502", "891", "892", "893"],
                    "223",
                    "alternative_version",
                ),
            ],
        )

    def test_alternative_setting_separates_local_branch(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("21")],
            [
                AnimeRelation("10", "20", "alternative_setting"),
                AnimeRelation("20", "21", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20", "21"}).groups

        branch = next(group for group in groups if group.root_media_id == "20")
        self.assertEqual(branch.group_kind, "alternative_branch")
        self.assertEqual(branch.member_media_ids, ["20", "21"])
        self.assertEqual(branch.context_parent_media_id, "10")
        self.assertEqual(branch.context_relation_type, "alternative_setting")

    def test_spin_off_separates_local_branch(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("21")],
            [
                AnimeRelation("10", "20", "spin_off"),
                AnimeRelation("20", "21", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20", "21"}).groups

        branch = next(group for group in groups if group.root_media_id == "20")
        self.assertEqual(branch.group_kind, "spin_off_branch")
        self.assertEqual(branch.member_media_ids, ["20", "21"])
        self.assertEqual(branch.context_parent_media_id, "10")
        self.assertEqual(branch.context_relation_type, "spin_off")

    def test_branch_boundary_wins_over_noisy_sequel_relation(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20")],
            [
                AnimeRelation("10", "20", "alternative_version"),
                AnimeRelation("10", "20", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20"}).groups

        self.assertEqual(
            [(group.root_media_id, group.group_kind) for group in groups],
            [("10", "singleton"), ("20", "alternative_branch")],
        )

    def test_alternative_setting_boundary_wins_over_noisy_sequel(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20")],
            [
                AnimeRelation("10", "20", "alternative_setting"),
                AnimeRelation("10", "20", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20"}).groups

        self.assertEqual(
            [(group.root_media_id, group.group_kind) for group in groups],
            [("10", "singleton"), ("20", "alternative_branch")],
        )

    def test_spin_off_boundary_wins_over_noisy_sequel(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20")],
            [
                AnimeRelation("10", "20", "spin_off"),
                AnimeRelation("10", "20", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20"}).groups

        self.assertEqual(
            [(group.root_media_id, group.group_kind) for group in groups],
            [("10", "singleton"), ("20", "spin_off_branch")],
        )

    def test_spin_off_boundary_blocks_indirect_sequel_rejoin(self):
        self._assert_indirect_boundary_rejoin_is_blocked(
            relation_type="spin_off",
            expected_group_kind="spin_off_branch",
        )

    def test_alternative_version_boundary_blocks_indirect_sequel_rejoin(self):
        self._assert_indirect_boundary_rejoin_is_blocked(
            relation_type="alternative_version",
            expected_group_kind="alternative_branch",
        )

    def test_alternative_setting_boundary_blocks_indirect_sequel_rejoin(self):
        self._assert_indirect_boundary_rejoin_is_blocked(
            relation_type="alternative_setting",
            expected_group_kind="alternative_branch",
        )

    def _assert_indirect_boundary_rejoin_is_blocked(
        self,
        *,
        relation_type,
        expected_group_kind,
    ):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("30")],
            [
                AnimeRelation("10", "20", relation_type),
                AnimeRelation("10", "30", "sequel"),
                AnimeRelation("30", "20", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10", "30"),
        )

        groups = self.resolver.resolve(snapshot, {"10", "20", "30"}).groups

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].member_media_ids, ["10", "30"])
        self.assertEqual(groups[1].member_media_ids, ["20"])
        self.assertEqual(groups[1].group_kind, expected_group_kind)
        self.assertEqual(groups[1].context_parent_media_id, "10")
        self.assertEqual(groups[1].context_relation_type, relation_type)

    def test_konosuba_explosion_is_a_separate_spin_off_branch(self):
        snapshot = self._snapshot(
            [
                self._node("30831", "KonoSuba"),
                self._node("51958", "KonoSuba: Explosion"),
            ],
            [AnimeRelation("30831", "51958", "spin_off")],
            root_media_id="30831",
            series_line_ids=("30831",),
        )

        groups = self.resolver.resolve(snapshot, {"30831", "51958"}).groups

        self.assertEqual(len(groups), 2)
        spin_off = groups[1]
        self.assertEqual(spin_off.root_media_id, "51958")
        self.assertEqual(spin_off.group_kind, "spin_off_branch")
        self.assertEqual(spin_off.context_parent_media_id, "30831")
        self.assertEqual(spin_off.context_relation_type, "spin_off")

    def test_prequel_and_sequel_keep_tracked_entries_in_one_local_group(self):
        nodes = [
            self._node("10", start_date=date(2020, 1, 1)),
            self._node("20", start_date=date(2021, 1, 1)),
            self._node("30", start_date=date(2022, 1, 1)),
        ]
        snapshot = self._snapshot(
            nodes,
            [
                AnimeRelation("20", "10", "prequel"),
                AnimeRelation("20", "30", "sequel"),
            ],
            root_media_id="20",
            series_line_ids=("10", "20", "30"),
        )

        resolution = self.resolver.resolve(snapshot, {"30", "10", "20"})

        self.assertEqual(len(resolution.groups), 1)
        self.assertEqual(resolution.groups[0].root_media_id, "10")
        self.assertEqual(
            resolution.groups[0].member_media_ids,
            ["10", "20", "30"],
        )
        self.assertEqual(resolution.groups[0].group_kind, "main_continuity")

    def test_special_ova_and_tv_special_affiliate_with_known_local_parent(self):
        nodes = [
            self._node("10"),
            self._node("11", media_type="special"),
            self._node("12", media_type="ova"),
            self._node("13", media_type="tv_special"),
        ]
        snapshot = self._snapshot(
            nodes,
            [
                AnimeRelation("10", "11", "side_story"),
                AnimeRelation("10", "12", "other"),
                AnimeRelation("10", "13", "summary"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        resolution = self.resolver.resolve(snapshot, {"10", "11", "12", "13"})

        self.assertEqual(len(resolution.groups), 1)
        self.assertEqual(
            set(resolution.groups[0].member_media_ids),
            {"10", "11", "12", "13"},
        )

    def test_full_story_affiliates_with_known_local_parent(self):
        snapshot = self._snapshot(
            [
                self._node("10"),
                self._node("11", media_type="movie"),
            ],
            [AnimeRelation("11", "10", "full_story")],
            root_media_id="10",
            series_line_ids=("10",),
        )

        resolution = self.resolver.resolve(snapshot, {"10", "11"})

        self.assertEqual(len(resolution.groups), 1)
        self.assertEqual(set(resolution.groups[0].member_media_ids), {"10", "11"})

    def test_untracked_entry_can_connect_members_but_is_not_displayed(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("30")],
            [
                AnimeRelation("10", "20", "sequel"),
                AnimeRelation("20", "30", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10", "20", "30"),
        )

        resolution = self.resolver.resolve(snapshot, {"10", "30"})

        self.assertEqual(len(resolution.groups), 1)
        self.assertEqual(resolution.groups[0].member_media_ids, ["10", "30"])
        self.assertNotIn("20", resolution.groups[0].member_media_ids)

    def test_untracked_parent_can_provide_branch_context(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("21")],
            [
                AnimeRelation("10", "20", "alternative_version"),
                AnimeRelation("20", "21", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        resolution = self.resolver.resolve(snapshot, {"20", "21"})

        self.assertEqual(len(resolution.groups), 1)
        self.assertEqual(resolution.groups[0].member_media_ids, ["20", "21"])
        self.assertEqual(resolution.groups[0].context_parent_media_id, "10")
        self.assertNotIn("10", resolution.groups[0].member_media_ids)

    def test_spice_and_wolf_old_adaptation_stays_separate(self):
        nodes = [
            self._node(
                "2966",
                "Spice and Wolf",
                start_date=date(2008, 1, 9),
            ),
            self._node("5341", start_date=date(2009, 4, 9)),
            self._node("6007", media_type="ova", start_date=date(2009, 4, 30)),
            self._node(
                "51122",
                "Spice and Wolf: Merchant Meets the Wise Wolf",
                start_date=date(2024, 4, 2),
            ),
        ]
        snapshot = self._snapshot(
            nodes,
            [
                AnimeRelation("51122", "2966", "alternative_version"),
                AnimeRelation("2966", "5341", "sequel"),
                AnimeRelation("5341", "6007", "side_story"),
            ],
            root_media_id="51122",
            series_line_ids=("51122",),
        )

        resolution = self.resolver.resolve(
            snapshot,
            {"51122", "2966", "5341", "6007"},
        )

        self.assertEqual(resolution.groups[0].root_media_id, "51122")
        old_branch = next(
            group for group in resolution.groups if group.root_media_id == "2966"
        )
        self.assertEqual(old_branch.group_kind, "alternative_branch")
        self.assertEqual(old_branch.member_media_ids, ["2966", "5341", "6007"])
        self.assertEqual(old_branch.context_parent_media_id, "51122")
        self.assertEqual(old_branch.context_relation_type, "alternative_version")

    def test_shared_special_does_not_rejoin_alternative_branch_to_main(self):
        snapshot = self._snapshot(
            [
                self._node("10"),
                self._node("20"),
                self._node("21", media_type="special"),
            ],
            [
                AnimeRelation("10", "20", "alternative_version"),
                AnimeRelation("10", "21", "side_story"),
                AnimeRelation("20", "21", "side_story"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        resolution = self.resolver.resolve(snapshot, {"10", "20", "21"})

        self.assertEqual(len(resolution.groups), 2)
        self.assertEqual(resolution.groups[0].member_media_ids, ["10", "21"])
        self.assertEqual(resolution.groups[1].member_media_ids, ["20"])
        self.assertEqual(
            resolution.groups[1].context_relation_type,
            "alternative_version",
        )

    def test_tracked_local_prequel_beats_boundary_entry_as_branch_root(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("21")],
            [
                AnimeRelation("10", "21", "alternative_version"),
                AnimeRelation("21", "20", "prequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
            continuity_ids=("10", "20", "21"),
        )

        resolution = self.resolver.resolve(snapshot, {"10", "20", "21"})

        branch = resolution.groups[1]
        self.assertEqual(branch.root_media_id, "20")
        self.assertEqual(branch.member_media_ids, ["20", "21"])

    def test_result_is_stable_for_any_tracked_id_insertion_order(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20"), self._node("21")],
            [
                AnimeRelation("10", "20", "spin_off"),
                AnimeRelation("20", "21", "sequel"),
            ],
            root_media_id="10",
            series_line_ids=("10",),
        )

        first = self.resolver.resolve(snapshot, {"10", "20", "21"})
        second = self.resolver.resolve(snapshot, {"21", "10", "20"})

        self.assertEqual(first, second)

    def test_resolution_does_not_mutate_snapshot(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20")],
            [AnimeRelation("10", "20", "sequel")],
            root_media_id="10",
            series_line_ids=("10", "20"),
        )
        before = deepcopy(snapshot)

        self.resolver.resolve(snapshot, {"10", "20"})

        self.assertEqual(snapshot, before)

    def test_resolution_does_not_access_database_or_cache(self):
        snapshot = self._snapshot(
            [self._node("10"), self._node("20")],
            [AnimeRelation("10", "20", "sequel")],
            root_media_id="10",
            series_line_ids=("10", "20"),
        )

        with (
            patch.object(cache, "get") as cache_get,
            patch.object(cache, "set") as cache_set,
            patch.object(cache, "delete") as cache_delete,
        ):
            resolution = self.resolver.resolve(snapshot, {"10", "20"})

        self.assertEqual(len(resolution.groups), 1)
        cache_get.assert_not_called()
        cache_set.assert_not_called()
        cache_delete.assert_not_called()

    def test_empty_tracked_set_returns_empty_resolution(self):
        snapshot = self._snapshot(
            [self._node("10")],
            [],
            root_media_id="10",
            series_line_ids=("10",),
        )

        resolution = self.resolver.resolve(snapshot, set())

        self.assertEqual(resolution.groups, [])
        self.assertEqual(resolution.resolver_version, "v1")
