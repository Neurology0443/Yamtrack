# ruff: noqa: D101, D102, D103

from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)


def node(
    media_id,
    *,
    title=None,
    media_type="tv",
    start_year=2020,
    image=None,
):
    return AnimeNode(
        media_id=str(media_id),
        title=title or f"Anime {media_id}",
        source="mal",
        media_type=media_type,
        image=image or f"https://example.com/{media_id}.jpg",
        start_date=date(start_year, 1, 1),
    )


def snapshot(
    nodes,
    relations,
    *,
    series_line_ids=None,
    root_media_id=None,
    canonical_root_media_id=None,
):
    nodes_by_media_id = {item.media_id: item for item in nodes}
    for relation in relations:
        nodes_by_media_id[relation.source_media_id].relations.append(relation)
    root_id = str(root_media_id or nodes[0].media_id)
    series_ids = (
        [str(media_id) for media_id in series_line_ids]
        if series_line_ids is not None
        else [item.media_id for item in nodes]
    )
    return AnimeFranchiseSnapshot(
        root_node=nodes_by_media_id[root_id],
        nodes_by_media_id=nodes_by_media_id,
        all_normalized_relations=list(relations),
        continuity_component=list(nodes),
        series_line=[nodes_by_media_id[media_id] for media_id in series_ids],
        direct_anchors=[],
        direct_candidates=[],
        has_series_line=bool(series_ids),
        fallback_anchor_media_id=root_id,
        canonical_root_media_id=str(canonical_root_media_id or root_id),
    )


def relation(source, target, relation_type):
    return AnimeRelation(
        source_media_id=str(source),
        target_media_id=str(target),
        relation_type=relation_type,
    )


class AnimeSeriesViewProjectionBuilderTests(SimpleTestCase):
    def setUp(self):
        self.builder = AnimeSeriesViewProjectionBuilder()

    def test_rezero_groupable_relations_build_one_main_card(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("31240", title="Re:Zero", media_type="tv"),
                    node("36286", media_type="movie"),
                    node("38414", media_type="movie"),
                ],
                [
                    relation("31240", "36286", "side_story"),
                    relation("36286", "31240", "parent_story"),
                    relation("31240", "38414", "prequel"),
                    relation("38414", "31240", "sequel"),
                ],
                series_line_ids=["31240"],
            ),
            tracked_media_ids={"31240", "36286", "38414"},
        )

        self.assertEqual(len(projection.groups), 1)
        group = projection.groups[0]
        self.assertEqual(group.root_media_id, "31240")
        self.assertEqual(group.display_media_id, "31240")
        self.assertEqual(group.display.title, "Re:Zero")
        self.assertEqual(group.group_kind, "main_continuity")
        self.assertEqual(set(group.member_media_ids), {"31240", "36286", "38414"})
        self.assertIsNone(group.context_parent_media_id)
        self.assertIsNone(group.context_relation_type)

    def test_untracked_series_line_main_represents_tracked_prequel(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("31240", title="Re:Zero", media_type="tv"),
                    node("38414", media_type="movie", start_year=2019),
                ],
                [
                    relation("31240", "38414", "prequel"),
                    relation("38414", "31240", "sequel"),
                ],
                series_line_ids=["31240"],
            ),
            tracked_media_ids={"38414"},
        )

        group = projection.groups[0]
        self.assertEqual(group.root_media_id, "31240")
        self.assertEqual(group.display_media_id, "31240")
        self.assertEqual(group.display.title, "Re:Zero")
        self.assertEqual(group.member_media_ids, ("38414",))
        self.assertEqual(group.group_kind, "main_continuity")

    def test_season_two_only_uses_first_series_line_entry(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("1", title="Season 1", start_year=2008),
                    node("2", title="Season 2", start_year=2009),
                ],
                [relation("1", "2", "sequel")],
                series_line_ids=["1", "2"],
            ),
            tracked_media_ids={"2"},
        )

        group = projection.groups[0]
        self.assertEqual(group.root_media_id, "1")
        self.assertEqual(group.display_media_id, "1")
        self.assertEqual(group.member_media_ids, ("2",))

    def test_movie_prequel_does_not_replace_series_line_tv_root(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("9", media_type="movie", start_year=2018),
                    node("10", media_type="tv", start_year=2020),
                ],
                [relation("9", "10", "sequel")],
                series_line_ids=["10"],
                root_media_id="10",
            ),
            tracked_media_ids={"9", "10"},
        )

        self.assertEqual(projection.groups[0].root_media_id, "10")

    def test_spin_off_is_separate_with_snapshot_parent_context(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("1", title="Sword Art Online"),
                    node("2", title="Gun Gale Online"),
                ],
                [relation("1", "2", "spin_off")],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(projection.groups), 2)
        branch = next(
            group for group in projection.groups if group.root_media_id == "2"
        )
        self.assertEqual(branch.group_kind, "spin_off")
        self.assertEqual(branch.context_relation_type, "spin_off")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_parent_title, "Sword Art Online")

    def test_groupable_complement_does_not_cross_spin_off_boundary(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2")],
                [
                    relation("1", "2", "spin_off"),
                    relation("2", "1", "parent_story"),
                ],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(projection.groups), 2)

    def test_alternative_version_is_separate(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1", title="Sword Art Online"), node("2")],
                [relation("1", "2", "alternative_version")],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2"},
        )

        branch = next(
            group for group in projection.groups if group.root_media_id == "2"
        )
        self.assertEqual(branch.group_kind, "alternative_branch")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_parent_title, "Sword Art Online")
        self.assertEqual(branch.context_relation_type, "alternative_version")

    def test_alternative_branch_continuation_groups_with_branch_representative(
        self,
    ):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("1", title="Main TV"),
                    node("2", title="Alternative Movie 1", media_type="movie"),
                    node("3", title="Alternative Movie 2", media_type="movie"),
                ],
                [
                    relation("1", "2", "alternative_version"),
                    relation("2", "1", "alternative_version"),
                    relation("2", "3", "sequel"),
                    relation("3", "2", "prequel"),
                ],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"2", "3"},
        )

        self.assertEqual(len(projection.groups), 1)
        branch = projection.groups[0]
        self.assertEqual(branch.root_media_id, "2")
        self.assertEqual(branch.display_media_id, "2")
        self.assertEqual(branch.member_media_ids, ("2", "3"))
        self.assertEqual(branch.group_kind, "alternative_branch")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_parent_title, "Main TV")
        self.assertEqual(branch.context_relation_type, "alternative_version")

    def test_alternative_setting_is_separate(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2")],
                [relation("1", "2", "alternative_setting")],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2"},
        )

        branch = next(
            group for group in projection.groups if group.root_media_id == "2"
        )
        self.assertEqual(branch.context_relation_type, "alternative_setting")

    def test_groupable_noise_cannot_cross_alternative_boundary(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2")],
                [
                    relation("1", "2", "alternative_version"),
                    relation("1", "2", "side_story"),
                ],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(projection.groups), 2)

    def test_indirect_groupable_bridge_across_boundary_is_deterministic(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("3")],
                [
                    relation("3", "2", "side_story"),
                    relation("1", "2", "alternative_version"),
                    relation("1", "3", "side_story"),
                ],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        member_sets = {
            frozenset(group.member_media_ids) for group in projection.groups
        }
        self.assertEqual(
            member_sets,
            {frozenset({"1", "3"}), frozenset({"2"})},
        )

    def test_branch_tv_uses_canonical_root_when_both_are_in_series_line(self):
        for relation_type, expected_kind in (
            ("spin_off", "spin_off"),
            ("alternative_version", "alternative_branch"),
        ):
            with self.subTest(relation_type=relation_type):
                projection = self.builder.build(
                    snapshot=snapshot(
                        [
                            node("1", title="Main TV"),
                            node("2", title="Branch TV"),
                        ],
                        [relation("1", "2", relation_type)],
                        series_line_ids=["1", "2"],
                        root_media_id="1",
                        canonical_root_media_id="1",
                    ),
                    tracked_media_ids={"1", "2"},
                )

                branch = next(
                    group
                    for group in projection.groups
                    if group.root_media_id == "2"
                )
                self.assertEqual(branch.group_kind, expected_kind)
                self.assertEqual(branch.context_parent_media_id, "1")
                self.assertEqual(branch.context_parent_title, "Main TV")

    def test_ignored_relations_do_not_group_components(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("3")],
                [
                    relation("1", "2", "character"),
                    relation("1", "3", "other"),
                ],
                series_line_ids=["1"],
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(len(projection.groups), 3)

    def test_singleton_uses_tracked_node_metadata(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1", title="Standalone", media_type="movie")],
                [],
                series_line_ids=[],
            ),
            tracked_media_ids={"1"},
        )

        group = projection.groups[0]
        self.assertEqual(group.group_kind, "singleton")
        self.assertEqual(group.root_media_id, "1")
        self.assertEqual(group.display.title, "Standalone")

    def test_representative_prefers_tv_when_series_line_is_absent(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("1", media_type="movie", start_year=2018),
                    node("2", media_type="tv", start_year=2020),
                ],
                [relation("1", "2", "side_story")],
                series_line_ids=[],
            ),
            tracked_media_ids={"1"},
        )

        self.assertEqual(projection.groups[0].root_media_id, "2")

    def test_ambiguous_boundary_does_not_invent_parent_context(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("9")],
                [relation("1", "2", "spin_off")],
                series_line_ids=["9"],
                root_media_id="9",
                canonical_root_media_id="9",
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertTrue(
            all(group.context_parent_media_id is None for group in projection.groups)
        )

    def test_contradictory_branch_contexts_are_removed(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("3")],
                [
                    relation("1", "3", "spin_off"),
                    relation("2", "3", "alternative_version"),
                ],
                series_line_ids=["1", "2"],
                root_media_id="1",
            ),
            tracked_media_ids={"3"},
        )

        group = projection.groups[0]
        self.assertIsNone(group.context_parent_media_id)
        self.assertIsNone(group.context_relation_type)

    def test_empty_tracked_ids_return_empty_projection(self):
        projection = self.builder.build(
            snapshot=snapshot([node("1")], []),
            tracked_media_ids=set(),
        )

        self.assertEqual(projection.groups, ())
        self.assertEqual(projection.projection_version, "v2")
