# ruff: noqa: D102
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)
from app.services.anime_series_view_rules import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
)


class AnimeSeriesViewProjectionBuilderTests(SimpleTestCase):
    """Test canonical roots, controlled reroots, members, and singleton safety."""

    @staticmethod
    def node(media_id, *, media_type="tv", start_date=None):
        return AnimeNode(
            media_id=str(media_id),
            title=f"Anime {media_id}",
            source="mal",
            media_type=media_type,
            image=f"https://example.com/{media_id}.jpg",
            start_date=start_date,
        )

    @staticmethod
    def relation(source, target, relation_type):
        return AnimeRelation(
            source_media_id=str(source),
            target_media_id=str(target),
            relation_type=relation_type,
        )

    def snapshot(
        self,
        *,
        seed,
        nodes,
        series_line=(),
        relations=(),
        root_candidates=(),
        secondary_candidates=(),
        direct_candidates=(),
    ):
        return SimpleNamespace(
            root_node=nodes[str(seed)],
            nodes_by_media_id=nodes,
            series_line=list(series_line),
            all_normalized_relations=list(relations),
            root_story_parent_candidates=list(root_candidates),
            no_series_line_secondary_candidates=list(secondary_candidates),
            direct_candidates=list(direct_candidates),
        )

    def test_existing_series_line_uses_first_root_and_one_group(self):
        root = self.node("100", start_date=date(2010, 1, 1))
        sequel = self.node("101")
        spin_off = self.node("102", media_type="special")
        alternative = self.node("103", media_type="movie")
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("100", "102", "spin_off"),
            self.relation("100", "103", "alternative_version"),
        ]
        snapshot = self.snapshot(
            seed="101",
            nodes={
                node.media_id: node for node in (root, sequel, spin_off, alternative)
            },
            series_line=[root, sequel],
            relations=relations,
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("101")

        self.assertEqual(projection.root.media_id, "100")
        self.assertEqual(projection.root.title, "Anime 100")
        self.assertEqual(projection.member_media_ids, ("100", "101", "102", "103"))
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(projection.projection_version, PROJECTION_VERSION)
        self.assertFalse(projection.is_rerooted)

    def test_rezero_special_reroots_to_main_series_and_keeps_seed(self):
        special = self.node("36286", media_type="special")
        candidate = self.node("31240", start_date=date(2016, 4, 4))
        relation = self.relation("36286", "31240", "parent_story")
        initial = self.snapshot(
            seed="36286",
            nodes={"36286": special, "31240": candidate},
            relations=[relation],
            secondary_candidates=[relation],
        )
        canonical = self.snapshot(
            seed="31240",
            nodes={"31240": candidate},
            series_line=[candidate],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("36286")

        self.assertEqual(projection.root.media_id, "31240")
        self.assertIn("36286", projection.member_media_ids)
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertTrue(projection.is_rerooted)
        self.assertEqual(projection.reroot_relation_type, "parent_story")

    def test_sao_progressive_alternative_reroots_to_sao(self):
        progressive = self.node("50275", media_type="movie")
        sao = self.node("11757", start_date=date(2012, 7, 8))
        relation = self.relation("50275", "11757", "alternative_setting")
        initial = self.snapshot(
            seed="50275",
            nodes={"50275": progressive, "11757": sao},
            relations=[relation],
            direct_candidates=[relation],
        )
        canonical = self.snapshot(
            seed="11757",
            nodes={"11757": sao},
            series_line=[sao],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("50275")

        self.assertEqual(projection.root.media_id, "11757")
        self.assertEqual(projection.member_media_ids, ("11757", "50275"))
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)

    def test_sao_progressive_first_movie_reroots_to_sao(self):
        progressive = self.node("42916", media_type="movie")
        sao = self.node("11757", start_date=date(2012, 7, 8))
        relation = self.relation("42916", "11757", "alternative_version")
        initial = self.snapshot(
            seed="42916",
            nodes={"42916": progressive, "11757": sao},
            relations=[relation],
            secondary_candidates=[relation],
        )
        canonical = self.snapshot(
            seed="11757",
            nodes={"11757": sao},
            series_line=[sao],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("42916")

        self.assertEqual(projection.root.media_id, "11757")
        self.assertIn("42916", projection.member_media_ids)
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)

    def test_no_reliable_root_returns_explicit_singleton(self):
        seed = self.node("900", media_type="special")
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="900",
            nodes={"900": seed},
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("900")

        self.assertEqual(projection.root.media_id, "900")
        self.assertEqual(projection.member_media_ids, ("900",))
        self.assertEqual(projection.group_kind, GROUP_KIND_SINGLETON)

    def test_character_relation_does_not_reroot(self):
        seed = self.node("901", media_type="special")
        other = self.node("902")
        relation = self.relation("901", "902", "character")
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="901",
            nodes={"901": seed, "902": other},
            relations=[relation],
            secondary_candidates=[relation],
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("901")

        self.assertEqual(projection.group_kind, GROUP_KIND_SINGLETON)
        snapshot_service.build.assert_called_once()

    def test_reroot_is_never_chained(self):
        seed = self.node("903", media_type="special")
        candidate = self.node("904")
        relation = self.relation("903", "904", "side_story")
        initial = self.snapshot(
            seed="903",
            nodes={"903": seed, "904": candidate},
            relations=[relation],
            secondary_candidates=[relation],
        )
        ambiguous = self.snapshot(
            seed="904",
            nodes={"904": candidate},
            series_line=[],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, ambiguous]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("903")

        self.assertEqual(projection.root.media_id, "904")
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(snapshot_service.build.call_count, 2)

    def test_candidate_priority_prefers_parent_story(self):
        seed = self.node("905", media_type="special")
        parent = self.node("906", start_date=date(2020, 1, 1))
        alternative = self.node("907", start_date=date(2010, 1, 1))
        parent_relation = self.relation("905", "906", "full_story")
        alternative_relation = self.relation(
            "905",
            "907",
            "alternative_version",
        )
        initial = self.snapshot(
            seed="905",
            nodes={"905": seed, "906": parent, "907": alternative},
            relations=[parent_relation, alternative_relation],
            root_candidates=[parent_relation],
            secondary_candidates=[alternative_relation],
        )
        canonical = self.snapshot(
            seed="906",
            nodes={"906": parent},
            series_line=[parent],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("905")

        self.assertEqual(projection.root.media_id, "906")
