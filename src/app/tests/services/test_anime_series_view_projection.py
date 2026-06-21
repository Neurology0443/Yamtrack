# ruff: noqa: D102
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from app.anime_series_view_constants import (
    GROUP_KIND_FRANCHISE,
    GROUP_KIND_SINGLETON,
    PROJECTION_VERSION,
)
from app.services.anime_franchise_types import AnimeNode, AnimeRelation
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
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
        is_truncated=False,
    ):
        return SimpleNamespace(
            root_node=nodes[str(seed)],
            nodes_by_media_id=nodes,
            series_line=list(series_line),
            all_normalized_relations=list(relations),
            root_story_parent_candidates=list(root_candidates),
            no_series_line_secondary_candidates=list(secondary_candidates),
            direct_candidates=list(direct_candidates),
            is_truncated=is_truncated,
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
        snapshot_service.build.assert_called_once_with(
            "101",
            refresh_cache=False,
            include_series_view_branch_continuations=True,
        )

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

    def test_other_unsafe_relations_do_not_group(self):
        for relation_type in ("recommendation", "adaptation", "other"):
            with self.subTest(relation_type=relation_type):
                seed = self.node("920", media_type="special")
                other = self.node("921")
                relation = self.relation("920", "921", relation_type)
                snapshot_service = Mock()
                snapshot_service.build.return_value = self.snapshot(
                    seed="920",
                    nodes={"920": seed, "921": other},
                    relations=[relation],
                )

                projection = AnimeSeriesViewProjectionBuilder(
                    snapshot_service=snapshot_service
                ).build("920")

                self.assertEqual(
                    projection.group_kind,
                    GROUP_KIND_SINGLETON,
                )

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

        self.assertFalse(projection.is_confident)
        self.assertIsNone(projection.group_kind)
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

    def test_spin_off_with_local_series_line_reroots_to_older_main_root(self):
        spin_off = self.node("200", start_date=date(2020, 1, 1))
        main = self.node("100", start_date=date(2010, 1, 1))
        relation = self.relation("200", "100", "spin_off")
        initial = self.snapshot(
            seed="200",
            nodes={"100": main, "200": spin_off},
            series_line=[spin_off],
            relations=[relation],
            direct_candidates=[relation],
        )
        canonical = self.snapshot(
            seed="100",
            nodes={"100": main},
            series_line=[main],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("200")

        self.assertEqual(projection.root.media_id, "100")
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertTrue(projection.is_rerooted)
        self.assertIn("200", projection.member_media_ids)

    def test_alternative_ona_with_local_series_line_reroots_to_main_root(self):
        alternative = self.node(
            "300",
            media_type="ona",
            start_date=date(2021, 1, 1),
        )
        main = self.node("250", start_date=date(2015, 1, 1))
        relation = self.relation("300", "250", "alternative_version")
        initial = self.snapshot(
            seed="300",
            nodes={"250": main, "300": alternative},
            series_line=[alternative],
            relations=[relation],
            direct_candidates=[relation],
        )
        canonical = self.snapshot(
            seed="250",
            nodes={"250": main},
            series_line=[main],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("300")

        self.assertEqual(projection.root.media_id, "250")
        self.assertTrue(projection.is_rerooted)

    def test_seed_finds_root_through_groupable_component(self):
        spin_off_s2 = self.node("402", start_date=date(2022, 1, 1))
        spin_off_s1 = self.node("401", start_date=date(2020, 1, 1))
        main = self.node("400", start_date=date(2010, 1, 1))
        relations = [
            self.relation("402", "401", "prequel"),
            self.relation("401", "400", "spin_off"),
        ]
        initial = self.snapshot(
            seed="402",
            nodes={"400": main, "401": spin_off_s1, "402": spin_off_s2},
            series_line=[spin_off_s1, spin_off_s2],
            relations=relations,
        )
        canonical = self.snapshot(
            seed="400",
            nodes={"400": main},
            series_line=[main],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("402")

        self.assertEqual(projection.root.media_id, "400")
        self.assertEqual(
            projection.member_media_ids,
            ("400", "401", "402"),
        )

    def test_branch_continuation_members_stay_in_one_projection(self):
        main = self.node("500", start_date=date(2010, 1, 1))
        branch_s1 = self.node("501", start_date=date(2020, 1, 1))
        branch_s2 = self.node("502", start_date=date(2022, 1, 1))
        relations = [
            self.relation("500", "501", "spin_off"),
            self.relation("501", "502", "sequel"),
        ]
        snapshot = self.snapshot(
            seed="500",
            nodes={"500": main, "501": branch_s1, "502": branch_s2},
            series_line=[main],
            relations=relations,
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("500")

        self.assertEqual(projection.root.media_id, "500")
        self.assertEqual(
            projection.member_media_ids,
            ("500", "501", "502"),
        )

    def test_movie_only_continuity_projects_as_franchise(self):
        movie_a = self.node(
            "600",
            media_type="movie",
            start_date=date(2020, 1, 1),
        )
        movie_b = self.node(
            "601",
            media_type="movie",
            start_date=date(2022, 1, 1),
        )
        relation = self.relation("601", "600", "prequel")
        initial = self.snapshot(
            seed="601",
            nodes={"600": movie_a, "601": movie_b},
            relations=[relation],
        )
        canonical = self.snapshot(
            seed="600",
            nodes={"600": movie_a, "601": movie_b},
            relations=[self.relation("600", "601", "sequel")],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("601")

        self.assertEqual(projection.root.media_id, "600")
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(projection.member_media_ids, ("600", "601"))

    def test_ona_only_continuity_projects_as_franchise(self):
        ona_s1 = self.node("610", media_type="ona", start_date=date(2020, 1, 1))
        ona_s2 = self.node("611", media_type="ona", start_date=date(2022, 1, 1))
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="610",
            nodes={"610": ona_s1, "611": ona_s2},
            relations=[self.relation("610", "611", "sequel")],
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("610")

        self.assertEqual(projection.root.media_id, "610")
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(projection.member_media_ids, ("610", "611"))

    def test_ova_only_continuity_projects_as_franchise(self):
        ova_a = self.node("620", media_type="ova", start_date=date(2020, 1, 1))
        ova_b = self.node("621", media_type="ova", start_date=date(2022, 1, 1))
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="620",
            nodes={"620": ova_a, "621": ova_b},
            relations=[self.relation("620", "621", "sequel")],
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("620")

        self.assertEqual(projection.root.media_id, "620")
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(projection.member_media_ids, ("620", "621"))

    def test_weak_side_story_without_confirmation_is_unresolved(self):
        special = self.node("700", media_type="special")
        candidate = self.node("701")
        relation = self.relation("700", "701", "side_story")
        initial = self.snapshot(
            seed="700",
            nodes={"700": special, "701": candidate},
            relations=[relation],
        )
        ambiguous = self.snapshot(
            seed="701",
            nodes={"701": candidate},
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, ambiguous]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("700")

        self.assertFalse(projection.is_confident)
        self.assertIsNone(projection.group_kind)
        self.assertEqual(projection.skip_reason, "weak_reroot_unconfirmed")

    def test_truncated_weak_reroot_is_unresolved_despite_partial_continuity(self):
        seed = self.node("710", media_type="special")
        candidate = self.node("711")
        sequel = self.node("712")
        relation = self.relation("710", "711", "spin_off")
        initial = self.snapshot(
            seed="710",
            nodes={"710": seed, "711": candidate},
            relations=[relation],
        )
        canonical = self.snapshot(
            seed="711",
            nodes={"711": candidate, "712": sequel},
            relations=[self.relation("711", "712", "sequel")],
            is_truncated=True,
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("710")

        self.assertFalse(projection.is_confident)
        self.assertEqual(projection.skip_reason, "weak_reroot_unconfirmed")
