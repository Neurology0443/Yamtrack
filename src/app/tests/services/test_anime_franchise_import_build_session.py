# ruff: noqa: D101,D102
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.services.anime_franchise_import import AnimeFranchiseImportService


@dataclass
class DiscoveryStatsStub:
    baseline_created: bool = False


class AnimeFranchiseImportBuildSessionTests(TestCase):
    def test_import_uses_build_session_for_minimal_cache_series_and_discovery(self):
        user = get_user_model().objects.create_user(username="importer")
        due_seed = SimpleNamespace(user_id=user.id, seed_mal_id="50")
        snapshot = SimpleNamespace(continuity_component=[object(), object()])
        selection = SimpleNamespace(
            media_ids={"100"},
            fingerprint_payload={"ids": ["100"]},
        )
        profile = Mock()
        profile.component_root_media_id.return_value = "100"
        profile.select.return_value = selection
        profile.detail_cache_warm_media_ids.return_value = {"200"}
        state_service = Mock()
        state_service.select_due_seeds.return_value = ([due_seed], 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (Mock(), True, False)
        build_session = Mock()
        build_session.anime_minimal.return_value = {
            "media_id": "100",
            "title": "Imported",
            "image": "https://example.com/image.jpg",
            "details": {},
        }
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        cache_build_service = Mock()
        cache_build_service.build_and_save.return_value = {"built": True}
        series_view_refresh_service = Mock()
        discovery_service = Mock()
        discovery_service.process_snapshot.return_value = DiscoveryStatsStub(
            baseline_created=True,
        )

        with (
            patch(
                "app.services.anime_franchise_import.get_import_profile",
                return_value=profile,
            ),
            patch(
                "app.services.anime_franchise_import.Anime.objects.filter",
            ) as filter_mock,
            patch("app.providers.mal.anime_minimal") as anime_minimal_mock,
        ):
            filter_mock.return_value.exists.return_value = False
            service = AnimeFranchiseImportService(
                build_session=build_session,
                snapshot_service=snapshot_service,
                state_service=state_service,
                cache_build_service=cache_build_service,
                series_view_refresh_service=series_view_refresh_service,
                discovery_service=discovery_service,
            )
            service._create_anime_entry = Mock()

            stats = service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=False,
                limit=None,
                refresh_cache=False,
                user_ids=None,
            )

        anime_minimal_mock.assert_not_called()
        build_session.anime_minimal.assert_called_once_with(
            "100",
            refresh_cache=False,
        )
        cache_build_service.build_and_save.assert_any_call(
            "100",
            refresh_cache=False,
            force_cache_rebuild=True,
        )
        cache_build_service.build_and_save.assert_any_call(
            "200",
            refresh_cache=False,
            force_cache_rebuild=True,
        )
        series_view_refresh_service.refresh_for_media_ids.assert_called_once_with(
            user=user,
            media_ids={"100", "50"},
            refresh_cache=False,
        )
        discovery_service.process_snapshot.assert_called_once()
        self.assertIs(
            discovery_service.process_snapshot.call_args.kwargs["snapshot"],
            snapshot,
        )
        self.assertEqual(stats.cache_warm_built, 2)
        self.assertEqual(stats.cache_warm_scheduled, 0)
        self.assertEqual(stats.series_view_refreshes, 1)

    def test_import_refresh_cache_flag_is_explicitly_forwarded(self):
        user = get_user_model().objects.create_user(username="refresh-importer")
        due_seed = SimpleNamespace(user_id=user.id, seed_mal_id="50")
        snapshot = SimpleNamespace(continuity_component=[object()])
        selection = SimpleNamespace(media_ids={"100"}, fingerprint_payload={})
        profile = Mock()
        profile.component_root_media_id.return_value = "100"
        profile.select.return_value = selection
        profile.detail_cache_warm_media_ids.return_value = set()
        state_service = Mock()
        state_service.select_due_seeds.return_value = ([due_seed], 0)
        state_service.build_fingerprint.return_value = "fingerprint"
        state_service.record_success.return_value = (Mock(), True, False)
        build_session = Mock()
        build_session.anime_minimal.return_value = {
            "media_id": "100",
            "title": "Imported",
            "image": "https://example.com/image.jpg",
            "details": {},
        }
        snapshot_service = Mock()
        snapshot_service.build.return_value = snapshot
        cache_build_service = Mock()
        cache_build_service.build_and_save.return_value = {"built": True}
        series_view_refresh_service = Mock()

        with (
            patch(
                "app.services.anime_franchise_import.get_import_profile",
                return_value=profile,
            ),
            patch(
                "app.services.anime_franchise_import.Anime.objects.filter",
            ) as filter_mock,
        ):
            filter_mock.return_value.exists.return_value = False
            service = AnimeFranchiseImportService(
                build_session=build_session,
                snapshot_service=snapshot_service,
                state_service=state_service,
                cache_build_service=cache_build_service,
                series_view_refresh_service=series_view_refresh_service,
                discovery_service=Mock(
                    process_snapshot=Mock(
                        return_value=DiscoveryStatsStub(baseline_created=False),
                    ),
                ),
            )
            service._create_anime_entry = Mock()

            service.run(
                profile_key="satellites",
                dry_run=False,
                full_rescan=False,
                limit=None,
                refresh_cache=True,
                user_ids=None,
            )

        snapshot_service.build.assert_called_once_with("50", refresh_cache=True)
        build_session.anime_minimal.assert_called_once_with("100", refresh_cache=True)
        cache_build_service.build_and_save.assert_called_once_with(
            "100",
            refresh_cache=True,
            force_cache_rebuild=True,
        )
        series_view_refresh_service.refresh_for_media_ids.assert_called_once_with(
            user=user,
            media_ids={"100", "50"},
            refresh_cache=True,
        )
