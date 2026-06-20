# ruff: noqa: D101,D102,D103
from django.test import SimpleTestCase

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_local_series_branch_context import (
    AnimeLocalBranchContext,
    AnimeLocalSeriesBranchContextProjector,
)


def node(media_id, *, media_type="tv"):
    return AnimeNode(
        media_id=str(media_id),
        title=f"Anime {media_id}",
        source="mal",
        media_type=media_type,
        image="image",
        start_date=None,
    )


def snapshot(*, nodes, root_id, series_ids, direct_candidates):
    nodes_by_id = {item.media_id: item for item in nodes}
    return AnimeFranchiseSnapshot(
        root_node=nodes_by_id[root_id],
        nodes_by_media_id=nodes_by_id,
        all_normalized_relations=list(direct_candidates),
        continuity_component=list(nodes),
        series_line=[nodes_by_id[media_id] for media_id in series_ids],
        direct_anchors=[nodes_by_id[media_id] for media_id in series_ids],
        direct_candidates=list(direct_candidates),
        has_series_line=bool(series_ids),
        fallback_anchor_media_id=root_id,
        canonical_root_media_id=series_ids[0] if series_ids else root_id,
    )


class AnimeLocalSeriesBranchContextProjectorTests(SimpleTestCase):
    def test_projects_sao_progressive_as_alternative_branch(self):
        result = AnimeLocalSeriesBranchContextProjector().project(
            snapshot(
                nodes=[node("100"), node("101"), node("200", media_type="movie")],
                root_id="100",
                series_ids=("100", "101"),
                direct_candidates=(
                    AnimeRelation("100", "200", "alternative_version"),
                ),
            )
        )

        self.assertEqual(
            result,
            [AnimeLocalBranchContext("200", "100", "alternative_version")],
        )

    def test_projects_konosuba_bakuen_as_spin_off(self):
        result = AnimeLocalSeriesBranchContextProjector().project(
            snapshot(
                nodes=[node("30831"), node("51958")],
                root_id="30831",
                series_ids=("30831",),
                direct_candidates=(
                    AnimeRelation("30831", "51958", "spin_off"),
                ),
            )
        )

        self.assertEqual(
            result,
            [AnimeLocalBranchContext("51958", "30831", "spin_off")],
        )

    def test_projects_alternative_setting_on_candidate(self):
        result = AnimeLocalSeriesBranchContextProjector().project(
            snapshot(
                nodes=[node("1"), node("2", media_type="movie")],
                root_id="1",
                series_ids=("1",),
                direct_candidates=(
                    AnimeRelation("1", "2", "alternative_setting"),
                ),
            )
        )

        self.assertEqual(
            result,
            [AnimeLocalBranchContext("2", "1", "alternative_setting")],
        )

    def test_ignores_ambiguous_branch_types(self):
        result = AnimeLocalSeriesBranchContextProjector().project(
            snapshot(
                nodes=[node("1"), node("2")],
                root_id="1",
                series_ids=("1",),
                direct_candidates=(
                    AnimeRelation("1", "2", "spin_off"),
                    AnimeRelation("1", "2", "alternative_version"),
                ),
            )
        )

        self.assertEqual(result, [])
