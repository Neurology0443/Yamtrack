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

    def test_independent_alternative_ona_continuity_stays_local(self):
        alternative = self.node(
            "300",
            media_type="ona",
            start_date=date(2021, 1, 1),
        )
        alternative_s2 = self.node(
            "301",
            media_type="ona",
            start_date=date(2022, 1, 1),
        )
        main = self.node("250", start_date=date(2015, 1, 1))
        relations = [
            self.relation("300", "250", "alternative_version"),
            self.relation("300", "301", "sequel"),
        ]
        initial = self.snapshot(
            seed="300",
            nodes={"250": main, "300": alternative, "301": alternative_s2},
            series_line=[alternative, alternative_s2],
            relations=relations,
            direct_candidates=[relations[0]],
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = initial

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("300")

        self.assertEqual(projection.root.media_id, "300")
        self.assertEqual(projection.member_media_ids, ("300", "301"))
        self.assertFalse(projection.is_rerooted)

    def test_alternative_ona_satellite_without_local_line_still_reroots(self):
        alternative = self.node("310", media_type="ona")
        main = self.node("250", start_date=date(2015, 1, 1))
        relation = self.relation("310", "250", "alternative_version")
        initial = self.snapshot(
            seed="310",
            nodes={"250": main, "310": alternative},
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
        ).build("310")

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

    def test_independent_remake_continuity_stays_separate_from_old_series(self):
        old_s1 = self.node("2966", start_date=date(2008, 1, 1))
        old_ova = self.node("6007", media_type="ova", start_date=date(2009, 4, 1))
        old_s2 = self.node("5341", start_date=date(2009, 7, 1))
        old_special = self.node("6884", media_type="special")
        remake_s1 = self.node("51122", start_date=date(2024, 4, 1))
        remake_s2 = self.node("59928", start_date=date(2025, 1, 1))
        nodes = {
            node.media_id: node
            for node in (
                old_s1,
                old_ova,
                old_s2,
                old_special,
                remake_s1,
                remake_s2,
            )
        }
        relations = [
            self.relation("51122", "2966", "alternative_version"),
            self.relation("51122", "5341", "alternative_version"),
            self.relation("51122", "6007", "alternative_version"),
            self.relation("51122", "59928", "sequel"),
            self.relation("59928", "51122", "prequel"),
            self.relation("2966", "6007", "sequel"),
            self.relation("6007", "5341", "sequel"),
            self.relation("5341", "6884", "side_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="51122",
            nodes=nodes,
            series_line=[remake_s1, remake_s2],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("51122")

        self.assertTrue(projection.is_confident)
        self.assertEqual(projection.group_kind, GROUP_KIND_FRANCHISE)
        self.assertEqual(projection.root.media_id, "51122")
        self.assertEqual(projection.member_media_ids, ("51122", "59928"))
        self.assertFalse(projection.is_rerooted)

    def test_independent_remake_second_season_uses_local_remake_root(self):
        old_s1 = self.node("2966", start_date=date(2008, 1, 1))
        remake_s1 = self.node("51122", start_date=date(2024, 4, 1))
        remake_s2 = self.node("59928", start_date=date(2025, 1, 1))
        relations = [
            self.relation("51122", "2966", "alternative_version"),
            self.relation("51122", "59928", "sequel"),
            self.relation("59928", "51122", "prequel"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="59928",
            nodes={
                "2966": old_s1,
                "51122": remake_s1,
                "59928": remake_s2,
            },
            series_line=[remake_s1, remake_s2],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("59928")

        self.assertEqual(projection.root.media_id, "51122")
        self.assertEqual(projection.member_media_ids, ("51122", "59928"))

    def test_old_continuity_stays_separate_from_independent_remake(self):
        old_s1 = self.node("2966", start_date=date(2008, 1, 1))
        old_ova = self.node("6007", media_type="ova", start_date=date(2009, 4, 1))
        old_s2 = self.node("5341", start_date=date(2009, 7, 1))
        old_special = self.node("6884", media_type="special")
        remake_s1 = self.node("51122", start_date=date(2024, 4, 1))
        remake_s2 = self.node("59928", start_date=date(2025, 1, 1))
        relations = [
            self.relation("51122", "2966", "alternative_version"),
            self.relation("51122", "5341", "alternative_version"),
            self.relation("51122", "6007", "alternative_version"),
            self.relation("51122", "59928", "sequel"),
            self.relation("2966", "6007", "sequel"),
            self.relation("6007", "5341", "sequel"),
            self.relation("5341", "6884", "side_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="2966",
            nodes={
                node.media_id: node
                for node in (
                    old_s1,
                    old_ova,
                    old_s2,
                    old_special,
                    remake_s1,
                    remake_s2,
                )
            },
            series_line=[old_s1, old_s2],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("2966")

        self.assertEqual(projection.root.media_id, "2966")
        self.assertEqual(
            projection.member_media_ids,
            ("2966", "5341", "6007", "6884"),
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

    def test_alternative_boundary_propagation_cuts_local_non_series_line_member(
        self,
    ):
        old_s1 = self.node("2966", start_date=date(2008, 1, 1))
        old_ova = self.node("6007", media_type="ova", start_date=date(2009, 4, 1))
        old_s2 = self.node("5341", start_date=date(2009, 7, 1))
        remake_s1 = self.node("51122", start_date=date(2024, 4, 1))
        remake_s2 = self.node("59928", start_date=date(2025, 1, 1))
        relations = [
            self.relation("2966", "6007", "sequel"),
            self.relation("6007", "5341", "sequel"),
            self.relation("2966", "51122", "alternative_version"),
            self.relation("6007", "51122", "alternative_version"),
            self.relation("51122", "59928", "sequel"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="2966",
            nodes={
                node.media_id: node
                for node in (old_s1, old_ova, old_s2, remake_s1, remake_s2)
            },
            series_line=[old_s1, old_s2],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("2966")

        self.assertEqual(projection.root.media_id, "2966")
        self.assertEqual(projection.member_media_ids, ("2966", "5341", "6007"))

    def test_external_serial_propagation_keeps_unrelated_external_edges(
        self,
    ):
        local_s1 = self.node("100", start_date=date(2020, 1, 1))
        local_s2 = self.node("101", start_date=date(2021, 1, 1))
        external_root = self.node("200", start_date=date(2022, 1, 1))
        external_other = self.node("201", start_date=date(2023, 1, 1))
        external_unrelated = self.node("202", start_date=date(2024, 1, 1))
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("100", "200", "alternative_version"),
            self.relation("201", "200", "alternative_version"),
            self.relation("202", "200", "alternative_version"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="100",
            nodes={
                node.media_id: node
                for node in (
                    local_s1,
                    local_s2,
                    external_root,
                    external_other,
                    external_unrelated,
                )
            },
            series_line=[local_s1, local_s2],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("100")

        self.assertEqual(projection.root.media_id, "100")
        self.assertEqual(projection.member_media_ids, ("100", "101"))

    def test_local_non_boundary_alternative_can_propagate_external_boundary(
        self,
    ):
        main = self.node("100", start_date=date(2020, 1, 1))
        sequel = self.node("101", start_date=date(2021, 1, 1))
        branch = self.node("102", media_type="ova", start_date=date(2020, 6, 1))
        local_alternative = self.node(
            "103", media_type="ova", start_date=date(2020, 7, 1)
        )
        external = self.node("200", start_date=date(2024, 1, 1))
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("100", "102", "side_story"),
            self.relation("102", "103", "alternative_version"),
            self.relation("100", "200", "alternative_version"),
            self.relation("103", "200", "alternative_version"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="100",
            nodes={
                node.media_id: node
                for node in (main, sequel, branch, local_alternative, external)
            },
            series_line=[main, sequel],
            relations=relations,
        )

        builder = AnimeSeriesViewProjectionBuilder(snapshot_service=snapshot_service)
        snapshot = snapshot_service.build.return_value

        boundary_keys = builder._alternative_continuity_boundary_relation_keys(
            snapshot,
            "100",
        )
        projection = builder.build("100")

        self.assertIn("103", projection.member_media_ids)
        self.assertNotIn("200", projection.member_media_ids)
        self.assertIn(
            ("103", "200", "alternative_version"),
            boundary_keys,
        )

    def test_external_serial_ids_are_derived_from_local_component_not_series_line_only(
        self,
    ):
        series_s1 = self.node("100", start_date=date(2020, 1, 1))
        series_s2 = self.node("101", start_date=date(2021, 1, 1))
        external_root = self.node("200", start_date=date(2022, 1, 1))
        external_other = self.node("201", start_date=date(2023, 1, 1))
        local_seed = self.node("300", start_date=date(2018, 1, 1))
        local_s2 = self.node("301", start_date=date(2019, 1, 1))
        relations = [
            self.relation("300", "301", "sequel"),
            self.relation("100", "101", "sequel"),
            self.relation("100", "200", "alternative_version"),
            self.relation("201", "200", "alternative_version"),
        ]
        initial = self.snapshot(
            seed="300",
            nodes={
                node.media_id: node
                for node in (
                    series_s1,
                    series_s2,
                    external_root,
                    external_other,
                    local_seed,
                    local_s2,
                )
            },
            series_line=[series_s1, series_s2],
            relations=relations,
        )
        canonical = self.snapshot(
            seed="300",
            nodes={"300": local_seed, "301": local_s2},
            series_line=[local_seed, local_s2],
            relations=[self.relation("300", "301", "sequel")],
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [initial, canonical]

        builder = AnimeSeriesViewProjectionBuilder(snapshot_service=snapshot_service)
        boundary_keys = builder._alternative_continuity_boundary_relation_keys(
            initial,
            "300",
        )
        projection = builder.build("300")

        self.assertIn(
            ("100", "200", "alternative_version"),
            boundary_keys,
        )
        self.assertNotIn(
            ("201", "200", "alternative_version"),
            boundary_keys,
        )
        self.assertEqual(projection.root.media_id, "300")
        self.assertEqual(projection.member_media_ids, ("300", "301"))
        self.assertNotIn("200", projection.member_media_ids)
        self.assertNotIn("201", projection.member_media_ids)

    def test_dragon_ball_like_movie_and_special_alternatives_stay_grouped(self):
        main_tv = self.node("100", start_date=date(1986, 2, 1))
        z_tv = self.node("101", start_date=date(1989, 4, 1))
        movie_alt = self.node("200", media_type="movie")
        special_alt = self.node("201", media_type="special")
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("100", "200", "alternative_version"),
            self.relation("101", "201", "side_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="100",
            nodes={
                node.media_id: node for node in (main_tv, z_tv, movie_alt, special_alt)
            },
            series_line=[main_tv, z_tv],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("100")

        self.assertEqual(projection.root.media_id, "100")
        self.assertEqual(projection.member_media_ids, ("100", "101", "200", "201"))

    def test_fate_like_tv_alternative_without_local_serial_continuity_stays_grouped(
        self,
    ):
        seed = self.node("300", media_type="ona", start_date=date(2020, 1, 1))
        main = self.node("301", start_date=date(2014, 1, 1))
        relation = self.relation("300", "301", "alternative_version")
        canonical = self.snapshot(
            seed="301", nodes={"300": seed, "301": main}, relations=[relation]
        )
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            self.snapshot(
                seed="300", nodes={"300": seed, "301": main}, relations=[relation]
            ),
            canonical,
        ]

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("300")

        self.assertEqual(projection.root.media_id, "301")
        self.assertEqual(projection.member_media_ids, ("300", "301"))

    def test_naruto_like_long_series_with_movies_stays_one_projection(self):
        naruto = self.node("100", start_date=date(2002, 10, 1))
        shippuden = self.node("101", start_date=date(2007, 2, 1))
        movie_1 = self.node("200", media_type="movie")
        movie_2 = self.node("201", media_type="movie")
        special = self.node("202", media_type="special")
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("100", "200", "side_story"),
            self.relation("101", "201", "side_story"),
            self.relation("101", "202", "side_story"),
        ]
        snapshot_service = Mock()
        snapshot_service.build.return_value = self.snapshot(
            seed="100",
            nodes={
                node.media_id: node
                for node in (naruto, shippuden, movie_1, movie_2, special)
            },
            series_line=[naruto, shippuden],
            relations=relations,
        )

        projection = AnimeSeriesViewProjectionBuilder(
            snapshot_service=snapshot_service
        ).build("100")

        self.assertEqual(projection.root.media_id, "100")
        self.assertEqual(
            projection.member_media_ids, ("100", "101", "200", "201", "202")
        )

    def test_serial_alternative_continuity_stays_separate(
        self,
    ):
        tv_s1 = self.node("100", start_date=date(2006, 1, 1))
        tv_s2 = self.node("101", start_date=date(2008, 1, 1))
        alt_s1 = self.node("200", media_type="ona", start_date=date(2024, 1, 1))
        alt_s2 = self.node("201", media_type="ona", start_date=date(2025, 1, 1))
        # Synthetic Code Geass-like serial alternative continuity.
        # Real Code Geass behavior was manually validated in dev.
        relations = [
            self.relation("100", "101", "sequel"),
            self.relation("200", "201", "sequel"),
            self.relation("200", "100", "alternative_version"),
        ]
        nodes = {node.media_id: node for node in (tv_s1, tv_s2, alt_s1, alt_s2)}
        snapshot_service = Mock()
        snapshot_service.build.side_effect = [
            self.snapshot(
                seed="200",
                nodes=nodes,
                series_line=[alt_s1, alt_s2],
                relations=relations,
            ),
            self.snapshot(
                seed="100", nodes=nodes, series_line=[tv_s1, tv_s2], relations=relations
            ),
        ]
        builder = AnimeSeriesViewProjectionBuilder(snapshot_service=snapshot_service)

        alt_projection = builder.build("200")
        tv_projection = builder.build("100")

        self.assertEqual(alt_projection.root.media_id, "200")
        self.assertEqual(alt_projection.member_media_ids, ("200", "201"))
        self.assertEqual(tv_projection.root.media_id, "100")
        self.assertEqual(tv_projection.member_media_ids, ("100", "101"))

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
