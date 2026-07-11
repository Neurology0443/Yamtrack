# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceService


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
        snapshot = SimpleNamespace(canonical_root_media_id=canonical_media_id)
        graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=3,
        )
        canonical_snapshot = SimpleNamespace(canonical_root_media_id=canonical_media_id)
        canonical_graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=4,
        )
        canonical_snapshot_service = Mock()
        canonical_snapshot_service.build.return_value = canonical_snapshot
        canonical_snapshot_service.graph_builder = canonical_graph_builder
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_snapshot_service
        ui_payload = {"entries": [{"media_id": canonical_media_id}]}
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

        return AnimeFranchiseCacheBuildService(
            build_session=build_session,
        ).build_and_save_from_snapshot(
            media_id,
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=force_cache_rebuild,
        )

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
        snapshot = SimpleNamespace(canonical_root_media_id="100")
        graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=3,
        )
        snapshot_service = Mock()
        snapshot_service.graph_builder = graph_builder
        snapshot_service.build.return_value = snapshot
        build_session = Mock()
        build_session.refresh_cache = True
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
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
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
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
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

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_noncanonical_force_rebuild_runs_ui_pipeline_on_canonical_snapshot(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        # Regression shape mirroring Kimetsu no Yaiba without network/MAL calls:
        # Canonical root: 38000; seed selected by maintenance: 62546.
        # Incorrect previous canonical order: 59192, 62547, 62546.
        # Expected canonical order: 59192, 62546, 62547.
        source_snapshot = SimpleNamespace(canonical_root_media_id="38000")
        source_graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=3,
        )
        canonical_snapshot = SimpleNamespace(canonical_root_media_id="38000")
        canonical_graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=5,
        )
        canonical_snapshot_service = Mock()
        canonical_snapshot_service.build.return_value = canonical_snapshot
        canonical_snapshot_service.graph_builder = canonical_graph_builder
        build_session = Mock()
        build_session.refresh_cache = True
        build_session.snapshot_service.return_value = canonical_snapshot_service
        canonical_ui_payload = {
            "continuity_extras": [
                {"media_id": "40456"},
                {
                    "media_id": "59192",
                    "relation_source_media_id": "55701",
                },
                {
                    "media_id": "62546",
                    "relation_source_media_id": "59192",
                },
                {
                    "media_id": "62547",
                    "relation_source_media_id": "62546",
                },
            ],
        }
        serialized_payload = {"root_media_id": "38000"}
        canonical_payload = {
            "root_media_id": "38000",
            "canonical_root_media_id": "38000",
            "continuity_extras": canonical_ui_payload["continuity_extras"],
            "aliasable_media_ids": ["38000", "55701", "59192", "62546", "62547"],
        }
        mock_pipeline_class.return_value.run.return_value = canonical_ui_payload
        mock_serialize.return_value = serialized_payload
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "38000",
            canonical_payload["aliasable_media_ids"],
        )
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.replace_aliases.return_value = 4
        mock_build_scoped_payload.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session,
        ).build_and_save_from_snapshot(
            "62546",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        canonical_snapshot_service.build.assert_called_once_with(
            "38000",
            refresh_cache=True,
        )
        mock_pipeline_class.return_value.run.assert_called_once_with(canonical_snapshot)
        mock_serialize.assert_called_once_with(
            canonical_ui_payload, root_media_id="38000"
        )
        mock_build_scoped_payload.assert_called_once_with(
            source_snapshot,
            seed_media_id="62546",
        )
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2], ("38000", canonical_payload)
        )
        self.assertEqual(
            [entry["media_id"] for entry in canonical_payload["continuity_extras"]],
            ["40456", "59192", "62546", "62547"],
        )
        self.assertEqual(
            {
                entry["media_id"]: entry.get("relation_source_media_id")
                for entry in canonical_payload["continuity_extras"]
                if "relation_source_media_id" in entry
            },
            {"59192": "55701", "62546": "59192", "62547": "62546"},
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_canonical_seed_does_not_build_second_snapshot(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        snapshot = SimpleNamespace(canonical_root_media_id="38000")
        graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=5
        )
        build_session = Mock()
        build_session.refresh_cache = True
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "38000"}
        canonical_payload = {"root_media_id": "38000", "aliasable_media_ids": ["38000"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "38000",
            ["38000"],
        )
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_build_scoped_payload.return_value = None

        AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "38000",
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=True,
        )

        build_session.snapshot_service.assert_not_called()
        mock_pipeline_class.return_value.run.assert_called_once_with(snapshot)

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_canonical_snapshot_failure_does_not_save_seed_payload_as_canonical(
        self,
        mock_cache,
        mock_pipeline_class,
    ):
        source_snapshot = SimpleNamespace(canonical_root_media_id="38000")
        source_graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=3
        )
        canonical_snapshot_service = Mock()
        canonical_snapshot_service.build.side_effect = RuntimeError("canonical boom")
        build_session = Mock()
        build_session.refresh_cache = True
        build_session.snapshot_service.return_value = canonical_snapshot_service
        mock_cache.load_valid_alias_payload_for_media.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "62546",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertFalse(result["built"])
        self.assertEqual(result["error"], "canonical boom")
        mock_cache.mark_error.assert_called_once_with("62546", "canonical boom")
        mock_cache.save_payload.assert_not_called()
        mock_cache.replace_aliases.assert_not_called()
        mock_pipeline_class.return_value.run.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_truncated_noncanonical_snapshot_keeps_existing_single_snapshot_behavior(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_build_scoped_payload,
    ):
        snapshot = SimpleNamespace(canonical_root_media_id="38000")
        graph_builder = SimpleNamespace(
            truncated=True, truncation_reason="max_nodes", node_count=99
        )
        build_session = Mock()
        build_session.refresh_cache = True
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "38000"}
        canonical_payload = {"root_media_id": "62546", "aliasable_media_ids": ["62546"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "62546",
            ["62546"],
        )
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_build_scoped_payload.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "62546",
            snapshot=snapshot,
            graph_builder=graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        build_session.snapshot_service.assert_not_called()
        mock_pipeline_class.return_value.run.assert_called_once_with(snapshot)
        mock_cache.replace_aliases.assert_not_called()
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(mock_cache.save_payload.call_args.kwargs["truncated"], True)


class AnimeFranchiseMaintenanceCanonicalCacheTests(SimpleTestCase):
    @patch.object(
        AnimeFranchiseMaintenanceService, "_tracked_member_media_ids", return_value=()
    )
    @patch.object(AnimeFranchiseMaintenanceService, "_sync_snapshot_images_if_fresh")
    @patch("app.services.anime_franchise_maintenance.summarize_franchise_activity")
    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_process_seed_passes_noncanonical_snapshot_to_shared_session_cache_builder(
        self,
        mock_build_session_class,
        mock_summarize,
        _mock_sync_images,
        _mock_tracked_ids,
    ):
        source_snapshot = SimpleNamespace(canonical_root_media_id="38000")
        source_graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=5
        )
        snapshot_service = Mock()
        snapshot_service.build.return_value = source_snapshot
        snapshot_service.graph_builder = source_graph_builder
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service
        mock_build_session_class.return_value = build_session
        mock_summarize.return_value = SimpleNamespace()
        discovery_service = Mock()
        discovery_service.build_snapshot_fingerprint.return_value = "fingerprint"
        cache_build_service = Mock()
        cache_build_service.build_and_save_from_snapshot.return_value = {
            "built": True,
            "canonical_media_id": "38000",
        }
        cache_build_service_factory = Mock(return_value=cache_build_service)
        user = SimpleNamespace(id=1)

        result = AnimeFranchiseMaintenanceService(
            discovery_service=discovery_service,
            cache_build_service_factory=cache_build_service_factory,
        ).process_seed(
            user=user,
            seed_mal_id="62546",
            refresh_cache=True,
            update_ui_cache=True,
            process_discovery=False,
            previous_fingerprint="fingerprint",
            refresh_series_view_on_change=False,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.cache_built)
        mock_build_session_class.assert_called_once_with(refresh_cache=True)
        cache_build_service_factory.assert_called_once_with(build_session)
        cache_build_service.build_and_save_from_snapshot.assert_called_once_with(
            "62546",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )
