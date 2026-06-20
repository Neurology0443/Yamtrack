# ruff: noqa: D101, D102, D103

from datetime import date

from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)


def node(media_id, *, media_type="tv", start_year=2020):
    return AnimeNode(
        media_id=str(media_id),
        title=f"Anime {media_id}",
        source="mal",
        media_type=media_type,
        image="https://example.com/image.jpg",
        start_date=date(start_year, 1, 1),
    )


def snapshot(nodes, relations):
    nodes_by_media_id = {item.media_id: item for item in nodes}
    for relation in relations:
        nodes_by_media_id[relation.source_media_id].relations.append(relation)
    root = nodes[0]
    return AnimeFranchiseSnapshot(
        root_node=root,
        nodes_by_media_id=nodes_by_media_id,
        all_normalized_relations=list(relations),
        continuity_component=list(nodes),
        series_line=list(nodes),
        direct_anchors=[],
        direct_candidates=[],
        has_series_line=True,
        fallback_anchor_media_id=root.media_id,
        canonical_root_media_id=root.media_id,
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

    def test_continuity_builds_one_group(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1", start_year=2020), node("2", start_year=2021)],
                [relation("1", "2", "sequel")],
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(projection.groups), 1)
        self.assertEqual(projection.groups[0].member_media_ids, ("1", "2"))
        self.assertEqual(projection.groups[0].group_kind, "main_continuity")

    def test_spin_off_is_separate_and_receives_context(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("3", start_year=2021)],
                [
                    relation("1", "2", "spin_off"),
                    relation("2", "3", "sequel"),
                ],
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(len(projection.groups), 2)
        branch = next(
            group for group in projection.groups if "2" in group.member_media_ids
        )
        self.assertEqual(branch.member_media_ids, ("2", "3"))
        self.assertEqual(branch.group_kind, "spin_off")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_relation_type, "spin_off")

    def test_alternative_version_is_separate(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2")],
                [relation("1", "2", "alternative_version")],
            ),
            tracked_media_ids={"1", "2"},
        )

        branch = next(
            group for group in projection.groups if group.root_media_id == "2"
        )
        self.assertEqual(branch.group_kind, "alternative_branch")
        self.assertEqual(branch.context_parent_media_id, "1")
        self.assertEqual(branch.context_relation_type, "alternative_version")

    def test_alternative_setting_is_separate(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2")],
                [relation("1", "2", "alternative_setting")],
            ),
            tracked_media_ids={"1", "2"},
        )

        branch = next(
            group for group in projection.groups if group.root_media_id == "2"
        )
        self.assertEqual(branch.context_relation_type, "alternative_setting")

    def test_noisy_continuity_cannot_cross_branch_boundary(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2"), node("3")],
                [
                    relation("1", "2", "alternative_version"),
                    relation("1", "3", "sequel"),
                    relation("2", "3", "prequel"),
                ],
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(len(projection.groups), 2)
        self.assertFalse(
            any(
                {"1", "2"} <= set(group.member_media_ids)
                for group in projection.groups
            )
        )

    def test_satellite_with_tracked_parent_is_attached(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2", media_type="special")],
                [relation("1", "2", "side_story")],
            ),
            tracked_media_ids={"1", "2"},
        )

        self.assertEqual(len(projection.groups), 1)
        self.assertEqual(projection.groups[0].root_media_id, "1")
        self.assertEqual(projection.groups[0].member_media_ids, ("1", "2"))

    def test_satellite_alone_keeps_parent_context(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [node("1"), node("2", media_type="special")],
                [relation("1", "2", "parent_story")],
            ),
            tracked_media_ids={"2"},
        )

        group = projection.groups[0]
        self.assertEqual(group.root_media_id, "2")
        self.assertEqual(group.group_kind, "satellite")
        self.assertEqual(group.context_parent_media_id, "1")
        self.assertEqual(group.context_relation_type, "parent_story")

    def test_display_prefers_first_tv_or_ona_in_logical_order(self):
        projection = self.builder.build(
            snapshot=snapshot(
                [
                    node("1", media_type="movie", start_year=2019),
                    node("2", media_type="tv", start_year=2020),
                    node("3", media_type="special", start_year=2021),
                ],
                [
                    relation("1", "2", "sequel"),
                    relation("2", "3", "side_story"),
                ],
            ),
            tracked_media_ids={"1", "2", "3"},
        )

        self.assertEqual(projection.groups[0].display_media_id, "2")

    def test_empty_tracked_ids_return_empty_projection(self):
        projection = self.builder.build(
            snapshot=snapshot([node("1")], []),
            tracked_media_ids=set(),
        )

        self.assertEqual(projection.groups, ())
        self.assertEqual(projection.projection_version, "v1")
