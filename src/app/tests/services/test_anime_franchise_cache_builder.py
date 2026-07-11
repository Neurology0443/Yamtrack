# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from app.services import anime_franchise_cache
from app.services.anime_franchise_build_session import (
    AnimeFranchiseBuildSession,
    AnimeFranchiseHydrationContext,
)
from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService
from app.services.anime_franchise_context import serialize_franchise_payload
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceService
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline


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
            refresh_cache=True,
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
        mock_build_scoped_payload.assert_not_called()
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
            refresh_cache=True,
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
    @patch("app.services.anime_franchise_maintenance.time.monotonic")
    @patch("app.services.anime_franchise_maintenance.AnimeFranchiseBuildSession")
    def test_process_seed_passes_refresh_policy_to_cache_builder(
        self,
        mock_build_session_class,
        mock_monotonic,
        mock_summarize,
        _mock_sync_images,
        _mock_tracked_ids,
    ):
        for refresh_cache in (True, False):
            with self.subTest(refresh_cache=refresh_cache):
                mock_monotonic.return_value = 123.45
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
                discovery_service.build_snapshot_fingerprint.return_value = (
                    "fingerprint"
                )
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
                    refresh_cache=refresh_cache,
                    update_ui_cache=True,
                    process_discovery=False,
                    previous_fingerprint="fingerprint",
                    refresh_series_view_on_change=False,
                )

                self.assertTrue(result.ok)
                self.assertTrue(result.cache_built)
                mock_build_session_class.assert_called_once_with(
                    refresh_cache=refresh_cache
                )
                cache_build_service_factory.assert_called_once_with(build_session)
                cache_build_service.build_and_save_from_snapshot.assert_called_once_with(
                    "62546",
                    snapshot=source_snapshot,
                    graph_builder=source_graph_builder,
                    refresh_cache=refresh_cache,
                    force_cache_rebuild=True,
                    started_at=123.45,
                )
                mock_monotonic.assert_called_once_with()
                mock_build_session_class.reset_mock()
                mock_monotonic.reset_mock()


class AnimeFranchiseCacheBuilderRealPipelineTests(SimpleTestCase):
    ROOT = "38000"
    LAST_TV = "55701"
    MOVIE_1 = "59192"
    MOVIE_2 = "62546"
    MOVIE_3 = "62547"
    SPECIAL = "40456"

    def _metadata(self):
        def anime(media_id, media_type, relations, *, title=None, start_date=None):
            return {
                "media_id": str(media_id),
                "title": title or f"Title {media_id}",
                "source": "mal",
                "image": f"img-{media_id}",
                "details": {
                    "raw_media_type": media_type,
                    "start_date": start_date,
                    "runtime": "24 min",
                    "episodes": 1,
                },
                "related": {
                    "related_anime": [
                        {"media_id": target, "relation_type": relation_type}
                        for target, relation_type in relations
                    ],
                },
            }

        return {
            self.ROOT: anime(
                self.ROOT,
                "tv",
                [(self.LAST_TV, "sequel")],
                title="Synthetic Root",
                start_date="2019-01-01",
            ),
            self.LAST_TV: anime(
                self.LAST_TV,
                "tv",
                [
                    (self.ROOT, "prequel"),
                    (self.MOVIE_1, "sequel"),
                    (self.SPECIAL, "side_story"),
                ],
                title="Synthetic Last TV",
                start_date="2020-01-01",
            ),
            self.SPECIAL: anime(
                self.SPECIAL,
                "movie",
                [],
                title="Synthetic Special",
                start_date="2020-06-01",
            ),
            self.MOVIE_1: anime(
                self.MOVIE_1,
                "movie",
                [(self.LAST_TV, "prequel"), (self.MOVIE_2, "sequel")],
                title="Synthetic Movie 1",
            ),
            # Movie 2 exposes movie 3 before movie 1. A raw snapshot from this seed
            # reproduces the perspective bug: movie 3 can be encountered before
            # movie 2 is promoted as the representative target.
            self.MOVIE_2: anime(
                self.MOVIE_2,
                "movie",
                [(self.MOVIE_3, "sequel"), (self.MOVIE_1, "prequel")],
                title="Synthetic Movie 2",
            ),
            self.MOVIE_3: anime(
                self.MOVIE_3,
                "movie",
                [(self.MOVIE_2, "prequel")],
                title="Synthetic Movie 3",
            ),
        }

    def _build_session(self, *, calls=None, refresh_cache=False):
        metadata = self._metadata()

        def fetcher(media_id, **kwargs):
            if calls is not None:
                calls.append((str(media_id), kwargs.get("refresh_cache")))
            return metadata[str(media_id)]

        return AnimeFranchiseBuildSession(
            refresh_cache=refresh_cache,
            max_nodes=0,
            hydration_context=AnimeFranchiseHydrationContext(anime_fetcher=fetcher),
        )

    def _snapshot(self, seed, *, build_session=None, refresh_cache=False):
        build_session = build_session or self._build_session(
            refresh_cache=refresh_cache
        )
        snapshot_service = build_session.snapshot_service()
        snapshot = snapshot_service.build(seed, refresh_cache=refresh_cache)
        return snapshot, snapshot_service.graph_builder

    def _continuity_entries(self, payload):
        return next(
            section["entries"]
            for section in payload["sections"]
            if section["key"] == "continuity_extras"
        )

    def _raw_continuity_order(self, seed):
        snapshot, _graph_builder = self._snapshot(seed)
        ui_payload = AnimeFranchiseUiPipeline().run(snapshot)
        serialized = anime_franchise_cache.prepare_payload_for_aliasing(
            serialize_franchise_payload(ui_payload, root_media_id=seed),
            build_seed_media_id=seed,
            truncated=False,
            aliases_enabled=True,
        )[0]
        return [entry["media_id"] for entry in self._continuity_entries(serialized)]

    def test_real_pipeline_raw_snapshots_reproduce_seed_perspective_bug(self):
        self.assertEqual(
            self._raw_continuity_order(self.ROOT),
            [self.MOVIE_1, self.MOVIE_2, self.MOVIE_3],
        )
        self.assertEqual(
            self._raw_continuity_order(self.MOVIE_2),
            [self.MOVIE_1, self.MOVIE_3, self.MOVIE_2],
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.save_payload"
    )
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.replace_aliases"
    )
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.load_valid_alias_payload_for_media"
    )
    def test_real_pipeline_forced_rebuild_saves_identical_payloads(
        self,
        mock_load_alias,
        mock_replace_aliases,
        mock_save_payload,
    ):
        mock_load_alias.return_value = None
        mock_replace_aliases.return_value = 4
        saved_payloads = []
        for seed in [self.ROOT, self.LAST_TV, self.MOVIE_1, self.MOVIE_2, self.MOVIE_3]:
            build_session = self._build_session()
            snapshot, graph_builder = self._snapshot(seed, build_session=build_session)
            mock_save_payload.reset_mock()

            result = AnimeFranchiseCacheBuildService(
                build_session=build_session
            ).build_and_save_from_snapshot(
                seed,
                snapshot=snapshot,
                graph_builder=graph_builder,
                refresh_cache=False,
                force_cache_rebuild=True,
            )

            self.assertTrue(result["built"], seed)
            canonical_save = mock_save_payload.call_args_list[0]
            self.assertEqual(canonical_save.args[0], self.ROOT)
            saved_payloads.append(canonical_save.args[1])

        first_payload = saved_payloads[0]
        for payload in saved_payloads:
            self.assertEqual(payload, first_payload)
            self.assertEqual(payload["root_media_id"], self.ROOT)
            self.assertEqual(payload["canonical_root_media_id"], self.ROOT)
            entries = self._continuity_entries(payload)
            self.assertEqual(
                [entry["media_id"] for entry in entries],
                [self.MOVIE_1, self.MOVIE_2, self.MOVIE_3],
            )
            self.assertEqual(
                {
                    entry["media_id"]: entry.get("relation_source_media_id")
                    for entry in entries
                },
                {
                    self.MOVIE_1: self.LAST_TV,
                    self.MOVIE_2: self.MOVIE_1,
                    self.MOVIE_3: self.MOVIE_2,
                },
            )
            self.assertIn(self.MOVIE_2, payload["aliasable_media_ids"])
            self.assertIn(self.MOVIE_3, payload["covered_media_ids"])

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.save_payload"
    )
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.replace_aliases"
    )
    @patch(
        "app.services.anime_franchise_cache_builder.anime_franchise_cache.load_valid_alias_payload_for_media"
    )
    def test_build_and_save_explicit_refresh_cache_wins_for_canonical_rebuild(
        self,
        mock_load_alias,
        _mock_replace_aliases,
        _mock_save_payload,
    ):
        mock_load_alias.return_value = None
        for session_default, explicit_refresh in [(False, True), (True, False)]:
            calls = []
            build_session = self._build_session(
                calls=calls,
                refresh_cache=session_default,
            )
            AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
                self.MOVIE_2,
                refresh_cache=explicit_refresh,
                force_cache_rebuild=True,
            )
            root_calls = [
                refresh for media_id, refresh in calls if media_id == self.ROOT
            ]
            self.assertIn(explicit_refresh, root_calls)


class AnimeFranchiseCacheBuilderRobustnessTests(SimpleTestCase):
    def _source(self, *, canonical="100", truncated=False):
        return (
            SimpleNamespace(canonical_root_media_id=canonical),
            SimpleNamespace(
                truncated=truncated,
                truncation_reason="max_nodes" if truncated else "",
                node_count=3,
            ),
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_noncanonical_nonforced_existing_payload_does_not_rebuild_or_run_pipeline(
        self,
        mock_cache,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        existing_payload = {"aliasable_media_ids": ["100", "200"]}
        build_session = Mock()
        build_session.refresh_cache = False
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.load_payload.return_value = (existing_payload, {"meta": True})
        mock_cache.replace_aliases.return_value = 2
        mock_scoped.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=False,
        )

        self.assertTrue(result["built"])
        build_session.snapshot_service.assert_not_called()
        mock_pipeline_class.return_value.run.assert_not_called()
        mock_cache.replace_aliases.assert_called_once_with(
            "100", existing_payload, truncated=False
        )
        mock_cache.save_payload.assert_not_called()
        mock_cache.delete_direct_payload.assert_called_once_with("200")

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_noncanonical_nonforced_missing_payload_schedules_without_rebuild(
        self,
        mock_cache,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        build_session = Mock()
        build_session.refresh_cache = False
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_cache.load_payload.return_value = (None, {"meta": True})
        scoped_payload = {"root_media_id": "200", "aliasable_media_ids": ["200"]}
        mock_scoped.return_value = scoped_payload
        mock_cache.extract_payload_media_ids.return_value = {"200"}

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=False,
        )

        self.assertTrue(result["built"])
        build_session.snapshot_service.assert_not_called()
        mock_pipeline_class.return_value.run.assert_not_called()
        mock_cache.maybe_schedule_build.assert_called_once_with(
            "100", {"meta": True}, has_payload=False
        )
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2], ("200", scoped_payload)
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_aliases_disabled_keeps_seed_local_payload(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        build_session = Mock()
        ui_payload = {"entries": [{"media_id": "200"}]}
        seed_payload = {"root_media_id": "200", "canonical_root_media_id": "200"}
        mock_pipeline_class.return_value.run.return_value = ui_payload
        mock_serialize.return_value = {"root_media_id": "200"}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            seed_payload,
            "200",
            {"200"},
        )
        mock_scoped.return_value = None

        AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        build_session.snapshot_service.assert_not_called()
        mock_pipeline_class.return_value.run.assert_called_once_with(source_snapshot)
        mock_serialize.assert_called_once_with(ui_payload, root_media_id="200")
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2], ("200", seed_payload)
        )
        mock_cache.replace_aliases.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_forced_canonical_rebuild_truncated_fails_without_writes(
        self,
        mock_cache,
        mock_pipeline_class,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=True, truncation_reason="max_nodes", node_count=2
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_cache.load_valid_alias_payload_for_media.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertFalse(result["built"])
        self.assertIn("canonical_snapshot_truncated", result["error"])
        mock_cache.mark_error.assert_called_once()
        mock_cache.save_payload.assert_not_called()
        mock_cache.replace_aliases.assert_not_called()
        mock_cache.delete_direct_payload.assert_not_called()
        mock_pipeline_class.return_value.run.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_forced_canonical_rebuild_root_change_fails_without_recursion(
        self, mock_cache
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="300"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=2
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_cache.load_valid_alias_payload_for_media.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertFalse(result["built"])
        self.assertEqual(result["error"], "canonical_root_changed")
        canonical_service.build.assert_called_once_with("100", refresh_cache=False)
        mock_cache.save_payload.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch("app.services.anime_franchise_cache_builder.time.monotonic")
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_duration_includes_canonical_rebuild_before_save(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
        mock_monotonic,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=5
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_monotonic.side_effect = [105, 106]
        mock_cache.load_valid_alias_payload_for_media.return_value = None
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )
        mock_scoped.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
            started_at=100,
        )

        self.assertTrue(result["built"])
        self.assertEqual(
            mock_cache.save_payload.call_args.kwargs["build_duration_seconds"], 5
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_scoped_builder_not_called_for_canonical_seed(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )

        result = AnimeFranchiseCacheBuildService(
            build_session=Mock()
        ).build_and_save_from_snapshot(
            "100",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        mock_scoped.assert_not_called()
        mock_cache.save_payload.assert_called_once()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_scoped_builder_not_called_for_aliasable_seed_even_if_it_would_fail(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_snapshot = SimpleNamespace(canonical_root_media_id="100")
        canonical_service = Mock()
        canonical_service.build.return_value = canonical_snapshot
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=4,
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {
            "root_media_id": "100",
            "aliasable_media_ids": ["100", "200"],
        }
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100", "200"},
        )
        mock_scoped.side_effect = RuntimeError("scoped boom")

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        mock_cache.delete_direct_payload.assert_called_once_with("200")
        mock_scoped.assert_not_called()
        save_calls = [call.args[0] for call in mock_cache.save_payload.call_args_list]
        self.assertEqual(save_calls, ["100"])

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_explicit_refresh_cache_passed_to_second_canonical_build(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        for session_default, explicit_refresh in ((False, True), (True, False)):
            with self.subTest(
                session_default=session_default,
                explicit_refresh=explicit_refresh,
            ):
                source_snapshot, source_graph_builder = self._source(canonical="100")
                canonical_snapshot = SimpleNamespace(canonical_root_media_id="100")
                canonical_service = Mock()
                canonical_service.build.return_value = canonical_snapshot
                canonical_service.graph_builder = SimpleNamespace(
                    truncated=False,
                    truncation_reason="",
                    node_count=4,
                )
                build_session = Mock()
                build_session.refresh_cache = session_default
                build_session.snapshot_service.return_value = canonical_service
                mock_pipeline_class.return_value.run.return_value = {"entries": []}
                mock_serialize.return_value = {"root_media_id": "100"}
                canonical_payload = {
                    "root_media_id": "100",
                    "aliasable_media_ids": ["100", "200"],
                }
                mock_cache.prepare_payload_for_aliasing.return_value = (
                    canonical_payload,
                    "100",
                    {"100", "200"},
                )
                mock_scoped.return_value = None

                result = AnimeFranchiseCacheBuildService(
                    build_session=build_session
                ).build_and_save_from_snapshot(
                    "200",
                    snapshot=source_snapshot,
                    graph_builder=source_graph_builder,
                    refresh_cache=explicit_refresh,
                    force_cache_rebuild=True,
                )

                self.assertTrue(result["built"])
                canonical_service.build.assert_called_once_with(
                    "100",
                    refresh_cache=explicit_refresh,
                )
                mock_cache.reset_mock()
                mock_scoped.reset_mock()
                mock_pipeline_class.return_value.run.reset_mock()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_scoped_construction_error_happens_before_any_cache_write(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=4
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )
        mock_scoped.side_effect = RuntimeError("scoped prepare boom")

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertFalse(result["built"])
        self.assertEqual(result["error"], "scoped prepare boom")
        mock_cache.save_payload.assert_not_called()
        mock_cache.replace_aliases.assert_not_called()
        mock_cache.delete_direct_payload.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_nonaliasable_scoped_is_prepared_before_canonical_publish_then_saved(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        events = []
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=4
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        scoped_payload = {"root_media_id": "200", "aliasable_media_ids": ["200"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )
        mock_cache.extract_payload_media_ids.return_value = {"200"}
        def replace_aliases_side_effect(*_args, **_kwargs):
            events.append("replace")
            return 1

        def scoped_side_effect(*_args, **_kwargs):
            events.append("scoped_prepare")
            return scoped_payload

        def save_side_effect(media_id, *_args, **_kwargs):
            events.append(f"save:{media_id}")

        mock_cache.replace_aliases.side_effect = replace_aliases_side_effect

        mock_scoped.side_effect = scoped_side_effect
        mock_cache.save_payload.side_effect = save_side_effect

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        self.assertEqual(events, ["scoped_prepare", "save:100", "replace", "save:200"])
        self.assertEqual(
            mock_cache.save_payload.call_args_list[0].args[:2],
            ("100", canonical_payload),
        )
        self.assertEqual(
            mock_cache.save_payload.call_args_list[1].args[:2], ("200", scoped_payload)
        )

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_nonaliasable_without_scoped_publishes_only_canonical_payload(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=4
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )
        mock_scoped.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertTrue(result["built"])
        mock_cache.save_payload.assert_called_once()
        self.assertEqual(
            mock_cache.save_payload.call_args.args[:2], ("100", canonical_payload)
        )
        mock_cache.delete_direct_payload.assert_not_called()

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True)
    @patch(
        "app.services.anime_franchise_cache_builder.build_scoped_seed_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    @patch("app.services.anime_franchise_cache_builder.anime_franchise_cache")
    def test_scoped_write_failure_is_best_effort_and_retry_converges(
        self,
        mock_cache,
        mock_serialize,
        mock_pipeline_class,
        mock_scoped,
    ):
        source_snapshot, source_graph_builder = self._source(canonical="100")
        canonical_service = Mock()
        canonical_service.build.return_value = SimpleNamespace(
            canonical_root_media_id="100"
        )
        canonical_service.graph_builder = SimpleNamespace(
            truncated=False, truncation_reason="", node_count=4
        )
        build_session = Mock()
        build_session.refresh_cache = False
        build_session.snapshot_service.return_value = canonical_service
        mock_pipeline_class.return_value.run.return_value = {"entries": []}
        mock_serialize.return_value = {"root_media_id": "100"}
        canonical_payload = {"root_media_id": "100", "aliasable_media_ids": ["100"]}
        scoped_payload = {"root_media_id": "200", "aliasable_media_ids": ["200"]}
        mock_cache.prepare_payload_for_aliasing.return_value = (
            canonical_payload,
            "100",
            {"100"},
        )
        mock_cache.extract_payload_media_ids.return_value = {"200"}
        mock_scoped.return_value = scoped_payload
        save_attempts = []

        scoped_save_attempt = 2

        def save_side_effect(media_id, *_args, **_kwargs):
            save_attempts.append(media_id)
            if len(save_attempts) == scoped_save_attempt:
                error_message = "scoped write boom"
                raise RuntimeError(error_message)

        mock_cache.save_payload.side_effect = save_side_effect

        service = AnimeFranchiseCacheBuildService(build_session=build_session)
        first_result = service.build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )
        mock_cache.save_payload.side_effect = None
        second_result = service.build_and_save_from_snapshot(
            "200",
            snapshot=source_snapshot,
            graph_builder=source_graph_builder,
            force_cache_rebuild=True,
        )

        self.assertFalse(first_result["built"])
        self.assertEqual(first_result["error"], "scoped write boom")
        self.assertTrue(second_result["built"])
        final_saves = [
            call.args[:2] for call in mock_cache.save_payload.call_args_list[-2:]
        ]
        self.assertEqual(
            final_saves, [("100", canonical_payload), ("200", scoped_payload)]
        )
        self.assertGreaterEqual(mock_cache.replace_aliases.call_count, 2)
