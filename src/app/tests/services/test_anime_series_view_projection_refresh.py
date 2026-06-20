# ruff: noqa: D101, D102

from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from app.services.anime_series_view_projection import AnimeSeriesViewProjection
from app.services.anime_series_view_projection_persistence import (
    AnimeSeriesViewPersistenceStats,
)
from app.services.anime_series_view_projection_refresh import (
    AnimeSeriesViewProjectionRefreshService,
)


class AnimeSeriesViewProjectionRefreshTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=7)
        self.snapshot = SimpleNamespace(
            nodes_by_media_id={"1": object(), "2": object()}
        )
        self.snapshot_service = Mock()
        self.snapshot_service.build.return_value = self.snapshot
        self.builder = Mock()
        self.projection = AnimeSeriesViewProjection(
            groups=(),
            projection_version="v1",
        )
        self.builder.build.return_value = self.projection
        self.persistence = Mock()
        self.persistence.persist.return_value = AnimeSeriesViewPersistenceStats()
        self.tracked_fetcher = Mock(return_value={"1"})
        self.service = AnimeSeriesViewProjectionRefreshService(
            snapshot_service=self.snapshot_service,
            projection_builder=self.builder,
            persistence_service=self.persistence,
            tracked_ids_fetcher=self.tracked_fetcher,
        )

    def test_builds_snapshot_fetches_tracked_ids_and_persists(self):
        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.snapshot_service.build.assert_called_once_with(
            "1",
            refresh_cache=False,
        )
        self.tracked_fetcher.assert_called_once_with(
            user_id=7,
            media_ids=frozenset({"1", "2"}),
        )
        self.builder.build.assert_called_once_with(
            snapshot=self.snapshot,
            tracked_media_ids={"1"},
        )
        self.persistence.persist.assert_called_once_with(
            user=self.user,
            projection=self.projection,
            scope_media_ids=frozenset({"1", "2"}),
            dry_run=False,
        )
        self.assertEqual(stats.snapshots_refreshed, 1)

    def test_identical_snapshot_scopes_are_refreshed_once(self):
        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1", "2"},
        )

        self.assertEqual(self.snapshot_service.build.call_count, 2)
        self.assertEqual(self.builder.build.call_count, 1)
        self.assertEqual(self.persistence.persist.call_count, 1)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_errors_are_counted_and_logged(self):
        self.snapshot_service.build.side_effect = RuntimeError("boom")

        with self.assertLogs(
            "app.services.anime_series_view_projection_refresh",
            level="ERROR",
        ):
            stats = self.service.refresh_for_media_ids(
                user=self.user,
                media_ids={"1"},
            )

        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_dry_run_is_forwarded_to_persistence(self):
        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
            dry_run=True,
        )

        self.assertTrue(self.persistence.persist.call_args.kwargs["dry_run"])
