# ruff: noqa: D101,D102,D107
from datetime import date
from unittest.mock import Mock

from django.test import SimpleTestCase

from app.services.anime_franchise_import import AnimeFranchiseImportService, FranchiseImportStats
from app.services.anime_franchise_rules import SECTION_RULES, get_section_rules
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode
from app.services.anime_franchise_ui_profile import AnimeFranchiseUiBuilder, AnimeFranchiseUiProfile


class CompatShimsTests(SimpleTestCase):
    def _snapshot(self):
        root = AnimeNode(
            media_id="100",
            title="Series S1",
            source="mal",
            media_type="tv",
            image="img-100",
            start_date=date(2010, 1, 1),
            relations=[],
        )
        return AnimeFranchiseSnapshot(
            root_node=root,
            nodes_by_media_id={"100": root},
            all_normalized_relations=[],
            continuity_component=[root],
            series_line=[root],
            direct_anchors=[root],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="100",
            canonical_root_media_id="100",
        )

    def test_ui_profile_shim_exports_old_and_new_names(self):
        self.assertIs(AnimeFranchiseUiProfile, AnimeFranchiseUiBuilder)
        builder = AnimeFranchiseUiProfile()
        self.assertTrue(callable(builder.build_view_model))

    def test_ui_rules_shim_exports_symbols(self):
        self.assertTrue(isinstance(SECTION_RULES, list))
        self.assertTrue(isinstance(get_section_rules(), list))

    def test_import_shim_exports_symbols(self):
        service = AnimeFranchiseImportService(
            snapshot_service=Mock(),
            state_service=Mock(),
        )
        stats = FranchiseImportStats()
        self.assertIsInstance(service, AnimeFranchiseImportService)
        self.assertIsInstance(stats, FranchiseImportStats)

    def test_old_ui_profile_import_path_still_runs_builder(self):
        builder = AnimeFranchiseUiProfile()
        view_model = builder.build_view_model(self._snapshot())
        self.assertEqual(view_model.root_media_id, "100")
        self.assertEqual(len(view_model.sections), 3)
