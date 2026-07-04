# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService


class AnimeFranchiseCacheBuildServiceTests(SimpleTestCase):
    def _build_from_snapshot(
        self,
        *,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
        media_id,
        canonical_media_id,
        canonical_payload,
        existing_canonical_payload=None,
        scoped_payload=None,
        force_cache_rebuild=False,
    ):
        snapshot = SimpleNamespace()
        graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=3,
        )
        ui_payload = {"entries": [{"media_id": media_id}]}
        serialized = {
            "media_id": media_id,
            "entries": [],
            "aliasable_media_ids": canonical_payload.get("aliasable_media_ids", []),
        }
        mock_pipeline_class.return_value.run.return_value = ui_payload
        mock_serialize.return_value = serialized
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            canonical_media_id,
            canonical_payload.get("aliasable_media_ids", []),
        )
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.load_payload.return_value = (existing_canonical_payload, None)
        mock_cache.replace_aliases.return_value = 2
        mock_cache.extract_payload_media_ids.return_value = {
            str(entry_media_id)
            for entry_media_id in (scoped_payload or {}).get("aliasable_media_ids", [])
        }
        mock_build_scoped_payload.return_value = scoped_payload

        return AnimeFranchiseCacheBuildService().build_and_save_from_snapshot(
            media_id,
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=force_cache_rebuild,
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot")
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
    @patch("app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot")
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_force_cache_rebuild_from_noncanonical_seed_publishes_fresh_canonical_payload(  # noqa: E501
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        fresh_canonical_payload = {
            "media_id": "52299",
            "continuity_extras": [{"media_id": "64546"}],
            "aliasable_media_ids": ["52299", "58567", "64546"],
        }
        existing_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["52299", "58567"],
        }

        result = self._build_from_snapshot(
            mock_cache=mock_cache,
            mock_serialize=mock_serialize,
            mock_pipeline_class=mock_pipeline_class,
            mock_build_scoped_payload=mock_build_scoped_payload,
            media_id="58567",
            canonical_media_id="52299",
            canonical_payload=fresh_canonical_payload,
            existing_canonical_payload=existing_canonical_payload,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        self.assertEqual(result["canonical_media_id"], "52299")
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2],
            ("52299", fresh_canonical_payload),
        )
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            fresh_canonical_payload,
            truncated=False,
        )
        mock_cache.load_payload.assert_not_called()
        mock_cache.delete_direct_payload.assert_called_once_with("58567")
        self.assertNotIn(
            ("58567",),
            [call.args[:1] for call in mock_cache.save_payload.call_args_list],
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot")
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
        fresh_canonical_payload = {
            "media_id": "52299",
            "continuity_extras": [{"media_id": "64546"}],
            "aliasable_media_ids": ["52299", "58567", "64546"],
        }
        existing_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["52299", "58567"],
        }

        self._build_from_snapshot(
            mock_cache=mock_cache,
            mock_serialize=mock_serialize,
            mock_pipeline_class=mock_pipeline_class,
            mock_build_scoped_payload=mock_build_scoped_payload,
            media_id="58567",
            canonical_media_id="52299",
            canonical_payload=fresh_canonical_payload,
            existing_canonical_payload=existing_canonical_payload,
            force_cache_rebuild=False,
        )

        self.assertNotIn(
            ("52299", fresh_canonical_payload),
            [call.args[:2] for call in mock_cache.save_payload.call_args_list],
        )
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            existing_canonical_payload,
            truncated=False,
        )
        mock_cache.load_payload.assert_called_once_with("52299")

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot")
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_force_cache_rebuild_from_noncanonical_non_aliasable_seed_saves_scoped_payload(  # noqa: E501
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        fresh_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["52299", "64546"],
        }
        scoped_payload = {"media_id": "99999", "aliasable_media_ids": ["99999"]}

        self._build_from_snapshot(
            mock_cache=mock_cache,
            mock_serialize=mock_serialize,
            mock_pipeline_class=mock_pipeline_class,
            mock_build_scoped_payload=mock_build_scoped_payload,
            media_id="99999",
            canonical_media_id="52299",
            canonical_payload=fresh_canonical_payload,
            scoped_payload=scoped_payload,
            force_cache_rebuild=True,
        )

        save_calls = [call.args[:2] for call in mock_cache.save_payload.call_args_list]
        self.assertIn(("52299", fresh_canonical_payload), save_calls)
        self.assertIn(("99999", scoped_payload), save_calls)
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            fresh_canonical_payload,
            truncated=False,
        )
        mock_cache.load_payload.assert_not_called()
        mock_cache.delete_direct_payload.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot")
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_force_cache_rebuild_from_noncanonical_aliasable_seed_deletes_direct_payload(  # noqa: E501
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        fresh_canonical_payload = {
            "media_id": "52299",
            "aliasable_media_ids": ["52299", "58567", "64546"],
        }
        scoped_payload = {"media_id": "58567", "aliasable_media_ids": ["58567"]}

        self._build_from_snapshot(
            mock_cache=mock_cache,
            mock_serialize=mock_serialize,
            mock_pipeline_class=mock_pipeline_class,
            mock_build_scoped_payload=mock_build_scoped_payload,
            media_id="58567",
            canonical_media_id="52299",
            canonical_payload=fresh_canonical_payload,
            scoped_payload=scoped_payload,
            force_cache_rebuild=True,
        )

        save_calls = [call.args[:2] for call in mock_cache.save_payload.call_args_list]
        self.assertIn(("52299", fresh_canonical_payload), save_calls)
        self.assertNotIn(("58567", scoped_payload), save_calls)
        mock_cache.replace_aliases.assert_called_once_with(
            "52299",
            fresh_canonical_payload,
            truncated=False,
        )
        mock_cache.delete_direct_payload.assert_called_once_with("58567")
