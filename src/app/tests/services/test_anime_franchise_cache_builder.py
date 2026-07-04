# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService


class AnimeFranchiseCacheBuildServiceTests(SimpleTestCase):
    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_build_and_save_uses_snapshot_pipeline_aliasing_and_cache(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        snapshot = SimpleNamespace()
        graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=3,
        )
        snapshot_service = Mock()
        snapshot_service.graph_builder = graph_builder
        snapshot_service.build.return_value = snapshot
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service
        ui_payload = {"entries": [{"media_id": "100"}]}
        mock_pipeline_class.return_value.run.return_value = ui_payload
        serialized = {"media_id": "100", "entries": [], "aliasable_media_ids": ["100"]}
        mock_serialize.return_value = serialized
        canonical_payload = {"media_id": "100", "aliasable_media_ids": ["100"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            ["100"],
        )
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.replace_aliases.return_value = 1
        mock_build_scoped_payload.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session,
        ).build_and_save("100", refresh_cache=True)

        snapshot_service.build.assert_called_once_with("100", refresh_cache=True)
        mock_pipeline_class.return_value.run.assert_called_once_with(snapshot)
        mock_serialize.assert_called_once_with(ui_payload, root_media_id="100")
        mock_cache.prepare_payload_for_aliasing.assert_called_once_with(
            serialized,
            build_seed_media_id="100",
            truncated=False,
            aliases_enabled=True,
        )
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2],
            ("100", canonical_payload),
        )
        mock_cache.replace_aliases.assert_called_once_with(
            "100",
            canonical_payload,
            truncated=False,
        )
        self.assertNotIn("user", canonical_payload)
        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "100")

    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_build_and_save_marks_error_on_failure(
        self,
        mock_cache,
        mock_pipeline_class,
    ):
        snapshot_service = Mock()
        snapshot_service.graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=1,
        )
        snapshot_service.build.side_effect = RuntimeError("boom")
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session,
        ).build_and_save("100")

        mock_cache.mark_error.assert_called_once_with("100", "boom")
        self.assertFalse(result["built"])
        self.assertEqual(result["error"], "boom")
        mock_pipeline_class.return_value.run.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_force_cache_rebuild_from_noncanonical_seed_publishes_canonical(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        snapshot = SimpleNamespace()
        graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=3
        )
        fresh_canonical_payload = {
            "media_id": "52299",
            "entries": [{"media_id": "123"}, {"media_id": "64546"}],
            "aliasable_media_ids": ["123", "52299", "64546"],
        }
        stale_canonical_payload = {
            "media_id": "52299",
            "entries": [{"media_id": "123"}],
            "aliasable_media_ids": ["52299"],
        }
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"media_id": "123", "entries": []}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            fresh_canonical_payload,
            "52299",
            ["123", "52299", "64546"],
        )
        mock_cache.load_payload.return_value = (
            stale_canonical_payload,
            {"fetched_at": "old"},
        )
        mock_cache.replace_aliases.return_value = 3
        mock_build_scoped_payload.return_value = {"media_id": "123", "entries": []}

        result = AnimeFranchiseCacheBuildService().build_and_save_from_snapshot(
            "123",
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2],
            ("52299", fresh_canonical_payload),
        )
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            fresh_canonical_payload,
            truncated=False,
        )
        mock_cache.delete_direct_payload.assert_called_once_with("123")

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_noncanonical_seed_without_force_preserves_existing_canonical_payload(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        snapshot = SimpleNamespace()
        graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=3
        )
        fresh_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["123", "52299", "64546"],
        }
        existing_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["123", "52299"],
        }
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"media_id": "123", "entries": []}
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.prepare_payload_for_aliasing.return_value = (
            fresh_canonical_payload,
            "52299",
            ["123", "52299", "64546"],
        )
        mock_cache.load_payload.return_value = (existing_canonical_payload, {})
        mock_cache.replace_aliases.return_value = 2
        mock_build_scoped_payload.return_value = {"media_id": "123", "entries": []}

        result = AnimeFranchiseCacheBuildService().build_and_save_from_snapshot(
            "123",
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=False,
        )

        self.assertTrue(result["built"])
        mock_cache.save_payload.assert_not_called()
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            existing_canonical_payload,
            truncated=False,
        )
        mock_cache.delete_direct_payload.assert_called_once_with("123")
