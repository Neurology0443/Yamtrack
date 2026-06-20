# ruff: noqa: D101,D102,D103
from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import (
    AnimeBranchRelation,
    AnimeFranchiseSnapshot,
)
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_local_series_resolver import AnimeLocalSeriesResolver


def node(media_id, *, media_type="tv", start_date=None):
    return AnimeNode(
        media_id=str(media_id),
        title=f"Anime {media_id}",
        source="mal",
        media_type=media_type,
        image="image",
        start_date=start_date,
    )


def snapshot(
    *,
    root_id,
    nodes,
    relations,
    canonical_root_id=None,
    series_ids=(),
    branch_relations=(),
):
    nodes_by_id = {item.media_id: item for item in nodes}
    for relation in relations:
        nodes_by_id[relation.source_media_id].relations.append(relation)
    series_line = [nodes_by_id[media_id] for media_id in series_ids]
    return AnimeFranchiseSnapshot(
        root_node=nodes_by_id[root_id],
        nodes_by_media_id=nodes_by_id,
        all_normalized_relations=relations,
        continuity_component=list(nodes),
        series_line=series_line,
        direct_anchors=series_line or [nodes_by_id[root_id]],
        direct_candidates=[],
        has_series_line=bool(series_line),
        fallback_anchor_media_id=root_id,
        canonical_root_media_id=canonical_root_id or root_id,
        branch_relations=list(branch_relations),
    )


class AnimeLocalSeriesResolverTests(SimpleTestCase):
    def test_rezero_complete_is_one_group(self):
        media_ids = ["31240", "36286", "38414", "39587", "42203", "54857", "61316"]
        nodes = [
            node("31240", start_date=date(2016, 4, 4)),
            node("36286", media_type="movie", start_date=date(2018, 10, 6)),
            node("38414", media_type="movie", start_date=date(2019, 11, 8)),
            node("39587", start_date=date(2020, 7, 8)),
            node("42203", start_date=date(2021, 1, 6)),
            node("54857", start_date=date(2024, 10, 2)),
            node("61316", start_date=date(2026, 1, 1)),
        ]
        relations = [
            AnimeRelation("31240", "38414", "prequel"),
            AnimeRelation("38414", "31240", "sequel"),
            AnimeRelation("31240", "39587", "sequel"),
            AnimeRelation("39587", "42203", "sequel"),
            AnimeRelation("42203", "54857", "sequel"),
            AnimeRelation("54857", "61316", "sequel"),
            AnimeRelation("31240", "36286", "side_story"),
            AnimeRelation("36286", "31240", "parent_story"),
        ]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="31240",
                nodes=nodes,
                relations=relations,
                canonical_root_id="38414",
                series_ids=("38414", "31240", "39587", "42203", "54857", "61316"),
            ),
            tracked_media_ids=set(media_ids),
        )

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].root_media_id, "38414")
        self.assertEqual(result.groups[0].display_media_id, "31240")
        self.assertEqual(set(result.groups[0].member_media_ids), set(media_ids))
        self.assertEqual(result.groups[0].group_kind, "main_continuity")

    def test_overlord_uses_first_series_tv_as_display_media(self):
        media_ids = ["29803", "35073", "37675", "48895", "48896"]
        nodes = [
            node("29803", start_date=date(2015, 7, 7)),
            node("35073", start_date=date(2018, 1, 9)),
            node("37675", start_date=date(2018, 7, 10)),
            node("48895", start_date=date(2022, 7, 5)),
            node("48896", media_type="movie", start_date=date(2024, 9, 20)),
        ]
        relations = [
            AnimeRelation("29803", "35073", "sequel"),
            AnimeRelation("35073", "37675", "sequel"),
            AnimeRelation("37675", "48895", "sequel"),
            AnimeRelation("48895", "48896", "sequel"),
        ]

        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="29803",
                nodes=nodes,
                relations=relations,
                canonical_root_id="29803",
                series_ids=("29803", "35073", "37675", "48895", "48896"),
            ),
            tracked_media_ids=set(media_ids),
        )

        self.assertEqual(result.groups[0].root_media_id, "29803")
        self.assertEqual(result.groups[0].display_media_id, "29803")

    def test_display_media_falls_back_to_technical_root_without_tv_or_ona(self):
        nodes = [
            node("10", media_type="movie", start_date=date(2020, 1, 1)),
            node("20", media_type="special", start_date=date(2019, 1, 1)),
        ]
        relations = [AnimeRelation("10", "20", "prequel")]

        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="10",
                nodes=nodes,
                relations=relations,
                canonical_root_id="20",
                series_ids=("20", "10"),
            ),
            tracked_media_ids={"10", "20"},
        )

        group = result.groups[0]
        self.assertEqual(group.root_media_id, "20")
        self.assertEqual(group.display_media_id, "20")

    def test_satellite_uses_untracked_parent_as_context(self):
        nodes = [node("29803"), node("33372", media_type="special")]
        relations = [
            AnimeRelation("33372", "29803", "parent_story"),
            AnimeRelation("29803", "33372", "side_story"),
        ]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="29803",
                nodes=nodes,
                relations=relations,
                canonical_root_id="29803",
                series_ids=("29803",),
            ),
            tracked_media_ids={"33372"},
        )

        self.assertEqual(len(result.groups), 1)
        group = result.groups[0]
        self.assertEqual(group.member_media_ids, ("33372",))
        self.assertEqual(group.context_parent_media_id, "29803")
        self.assertIn(group.context_relation_type, {"parent_story", "side_story"})

    def test_spin_off_branch_stays_separate(self):
        nodes = [node("1"), node("2"), node("3")]
        relations = [
            AnimeRelation("1", "2", "spin_off"),
            AnimeRelation("2", "3", "sequel"),
        ]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="1",
                nodes=nodes,
                relations=relations,
                canonical_root_id="1",
                series_ids=("1",),
                branch_relations=(
                    AnimeBranchRelation("1", "2", "spin_off"),
                ),
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(
            {
                group.root_media_id: set(group.member_media_ids)
                for group in result.groups
            },
            {"1": {"1"}, "2": {"2", "3"}},
        )
        branch = next(group for group in result.groups if group.root_media_id == "2")
        self.assertEqual(branch.group_kind, "spin_off")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_relation_type, "spin_off")

    def test_konosuba_like_reverse_spin_off_edge_labels_spin_off_component(self):
        nodes = [
            node("30831", media_type="tv", start_date=date(2016, 1, 14)),
            node("51958", media_type="tv", start_date=date(2023, 4, 6)),
            node("57833", media_type="tv", start_date=date(2026, 1, 1)),
        ]
        relations = [
            AnimeRelation("51958", "30831", "spin_off"),
            AnimeRelation("51958", "57833", "sequel"),
        ]

        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="51958",
                nodes=nodes,
                relations=relations,
                canonical_root_id="51958",
                series_ids=("30831",),
                branch_relations=(
                    AnimeBranchRelation("30831", "51958", "spin_off"),
                ),
            ),
            tracked_media_ids={"30831", "51958", "57833"},
        )

        main_group = next(
            group for group in result.groups if "30831" in group.member_media_ids
        )
        spin_off_group = next(
            group for group in result.groups if "51958" in group.member_media_ids
        )
        self.assertIsNone(main_group.context_relation_type)
        self.assertEqual(spin_off_group.group_kind, "spin_off")
        self.assertEqual(spin_off_group.context_relation_type, "spin_off")
        self.assertEqual(spin_off_group.context_parent_media_id, "30831")

    def test_side_story_does_not_reconnect_spin_off_branches(self):
        nodes = [
            node("1"),
            node("2"),
            node("3"),
            node("4", media_type="special"),
        ]
        relations = [
            AnimeRelation("1", "2", "spin_off"),
            AnimeRelation("2", "3", "sequel"),
            AnimeRelation("1", "4", "side_story"),
            AnimeRelation("2", "4", "side_story"),
        ]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="1",
                nodes=nodes,
                relations=relations,
                canonical_root_id="1",
                series_ids=("1",),
            ),
            tracked_media_ids={"1", "2", "3", "4"},
        )

        self.assertEqual(len(result.groups), 2)
        self.assertFalse(
            any(
                {"1", "2"} <= set(group.member_media_ids)
                for group in result.groups
            )
        )

    def test_noisy_continuity_cannot_bridge_a_branch_boundary(self):
        nodes = [node("1"), node("2"), node("3")]
        relations = [
            AnimeRelation("1", "2", "alternative_version"),
            AnimeRelation("1", "3", "sequel"),
            AnimeRelation("2", "3", "prequel"),
        ]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="1",
                nodes=nodes,
                relations=relations,
                canonical_root_id="1",
                series_ids=("1", "3"),
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(len(result.groups), 2)
        self.assertFalse(
            any(
                {"1", "2"} <= set(group.member_media_ids)
                for group in result.groups
            )
        )

    def test_alternative_setting_is_a_separate_branch(self):
        nodes = [node("1"), node("2")]
        relations = [AnimeRelation("1", "2", "alternative_setting")]
        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="1",
                nodes=nodes,
                relations=relations,
                canonical_root_id="1",
                series_ids=("1",),
                branch_relations=(
                    AnimeBranchRelation("1", "2", "alternative_setting"),
                ),
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(result.groups), 2)
        alternative = next(
            group for group in result.groups if "2" in group.member_media_ids
        )
        self.assertEqual(alternative.group_kind, "alternative_branch")

    def test_alternative_context_stays_on_branch_when_canonical_root_is_alternative(
        self,
    ):
        nodes = [
            node("100", media_type="tv", start_date=date(2012, 7, 8)),
            node("101", media_type="tv", start_date=date(2014, 7, 5)),
            node("200", media_type="movie", start_date=date(2021, 10, 30)),
        ]
        relations = [
            AnimeRelation("100", "101", "sequel"),
            AnimeRelation("200", "100", "alternative_version"),
        ]

        result = AnimeLocalSeriesResolver().resolve(
            snapshot=snapshot(
                root_id="200",
                nodes=nodes,
                relations=relations,
                canonical_root_id="200",
                series_ids=("100", "101"),
                branch_relations=(
                    AnimeBranchRelation("100", "200", "alternative_version"),
                ),
            ),
            tracked_media_ids={"100", "101", "200"},
        )

        main_group = next(
            group for group in result.groups if "100" in group.member_media_ids
        )
        alternative_group = next(
            group for group in result.groups if "200" in group.member_media_ids
        )
        self.assertIsNone(main_group.context_relation_type)
        self.assertEqual(alternative_group.group_kind, "alternative_branch")
        self.assertEqual(
            alternative_group.context_relation_type,
            "alternative_version",
        )
        self.assertEqual(alternative_group.context_parent_media_id, "100")
