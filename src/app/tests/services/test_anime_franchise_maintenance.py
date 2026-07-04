# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryStats
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceService


class AnimeFranchiseMaintenanceServiceTests(SimpleTestCase):
    def _service_context(
        self,
        *,
        seed_mal_id="123",
        canonical_root_mal_id="52299",
        cache_results=None,
        discovery_stats=None,
        tracked_member_media_ids=("123",),
    ):
        user = SimpleNamespace(id=7)
        snapshot = SimpleNamespace(
            canonical_root_media_id=canonical_root_mal_id,
            nodes_by_media_id={seed_mal_id: SimpleNamespace(media_id=seed_mal_id)},
        )
        graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=2
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        snapshot_service.graph_builder = graph_builder
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service

        discovery_service = Mock()
        discovery_service.build_snapshot_fingerprint.return_value = "fingerprint"
        discovery_service.process_snapshot.return_value = (
            discovery_stats or AnimeFranchiseDiscoveryStats()
        )

        cache_service = Mock()
        cache_service.build_and_save_from_snapshot.side_effect = cache_results or [
            {"built": True}
        ]
        cache_factory = Mock(return_value=cache_service)

        series_refresh_service = Mock()
        series_refresh_service.refresh_for_media_ids.return_value = SimpleNamespace(
            errors=0
        )
        series_factory = Mock(return_value=series_refresh_service)

        service = AnimeFranchiseMaintenanceService(
            discovery_service=discovery_service,
            cache_build_service_factory=cache_factory,
            series_view_refresh_service_factory=series_factory,
        )
        service._tracked_member_media_ids = Mock(return_value=tracked_member_media_ids)
        return SimpleNamespace(
            user=user,
            service=service,
            snapshot=snapshot,
            snapshot_service=snapshot_service,
            build_session=build_session,
            graph_builder=graph_builder,
            discovery_service=discovery_service,
            cache_service=cache_service,
            series_refresh_service=series_refresh_service,
        )

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_post_baseline_discovery_syncs_canonical_cache_from_same_snapshot(
        self, mock_session_class
    ):
        ctx = self._service_context(
            discovery_stats=AnimeFranchiseDiscoveryStats(
                discoveries_created=1,
                baseline_created=0,
                notifications_queued=1,
            ),
            cache_results=[{"built": True}, {"built": True}],
        )
        mock_session_class.return_value = ctx.build_session

        result = ctx.service.process_seed(
            user=ctx.user,
            seed_mal_id="123",
            refresh_cache=False,
            update_ui_cache=True,
        )

        self.assertEqual(ctx.cache_service.build_and_save_from_snapshot.call_count, 2)
        first_call, second_call = (
            ctx.cache_service.build_and_save_from_snapshot.call_args_list
        )
        self.assertEqual(first_call.args[0], "123")
        self.assertEqual(second_call.args[0], "52299")
        self.assertIs(second_call.kwargs["snapshot"], ctx.snapshot)
        self.assertIs(second_call.kwargs["graph_builder"], ctx.graph_builder)
        self.assertTrue(second_call.kwargs["force_cache_rebuild"])
        self.assertTrue(result.post_discovery_cache_sync_attempted)
        self.assertTrue(result.post_discovery_cache_synced)
        self.assertEqual(result.discovery_notifications_queued, 1)
        self.assertEqual(result.discoveries_created, 1)

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_post_baseline_discovery_does_not_double_build_already_canonical_seed(
        self, mock_session_class
    ):
        ctx = self._service_context(
            seed_mal_id="52299",
            canonical_root_mal_id="52299",
            discovery_stats=AnimeFranchiseDiscoveryStats(discoveries_created=1),
            cache_results=[{"built": True}],
        )
        mock_session_class.return_value = ctx.build_session

        result = ctx.service.process_seed(
            user=ctx.user,
            seed_mal_id="52299",
            refresh_cache=False,
            update_ui_cache=True,
        )

        ctx.cache_service.build_and_save_from_snapshot.assert_called_once()
        self.assertTrue(result.post_discovery_cache_sync_attempted)
        self.assertTrue(result.post_discovery_cache_synced)

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_initial_baseline_does_not_trigger_post_discovery_cache_sync(
        self, mock_session_class
    ):
        ctx = self._service_context(
            discovery_stats=AnimeFranchiseDiscoveryStats(
                discoveries_created=2,
                baseline_created=1,
                notifications_queued=0,
            ),
            cache_results=[{"built": True}],
        )
        mock_session_class.return_value = ctx.build_session

        result = ctx.service.process_seed(
            user=ctx.user,
            seed_mal_id="123",
            refresh_cache=False,
            update_ui_cache=True,
        )

        ctx.cache_service.build_and_save_from_snapshot.assert_called_once()
        self.assertFalse(result.post_discovery_cache_sync_attempted)
        self.assertFalse(result.post_discovery_cache_synced)
        self.assertTrue(result.discovery_baseline_created)

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_notifications_disabled_discovery_still_syncs_canonical_cache(
        self, mock_session_class
    ):
        ctx = self._service_context(
            discovery_stats=AnimeFranchiseDiscoveryStats(
                discoveries_created=1,
                baseline_created=0,
                notifications_queued=0,
            ),
            cache_results=[{"built": True}, {"built": True}],
        )
        mock_session_class.return_value = ctx.build_session

        result = ctx.service.process_seed(
            user=ctx.user,
            seed_mal_id="123",
            refresh_cache=False,
            update_ui_cache=True,
        )

        self.assertEqual(ctx.cache_service.build_and_save_from_snapshot.call_count, 2)
        self.assertEqual(
            ctx.cache_service.build_and_save_from_snapshot.call_args_list[1].args[0],
            "52299",
        )
        self.assertTrue(result.post_discovery_cache_synced)

    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_post_baseline_discovery_refreshes_series_view_only_for_tracked_members(
        self, mock_session_class
    ):
        ctx = self._service_context(
            discovery_stats=AnimeFranchiseDiscoveryStats(
                discoveries_created=1,
                notifications_queued=1,
            ),
            tracked_member_media_ids=("123", "52299"),
            cache_results=[{"built": True}, {"built": True}],
        )
        mock_session_class.return_value = ctx.build_session

        result = ctx.service.process_seed(
            user=ctx.user,
            seed_mal_id="123",
            refresh_cache=False,
            update_ui_cache=True,
            refresh_series_view_on_change=False,
        )

        ctx.series_refresh_service.refresh_for_media_ids.assert_called_once_with(
            user=ctx.user,
            media_ids=("123", "52299"),
            refresh_cache=False,
        )
        self.assertNotEqual(
            ctx.series_refresh_service.refresh_for_media_ids.call_args.kwargs[
                "media_ids"
            ],
            ("64546",),
        )
        self.assertTrue(result.post_discovery_series_view_refresh_requested)
