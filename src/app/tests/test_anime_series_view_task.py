# ruff: noqa: D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshStats,
)
from app.tasks import refresh_anime_series_view_franchise_projection


class AnimeSeriesViewTaskTests(TestCase):
    """Test task normalization, skips, service calls, and returned statistics."""

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeSeriesViewFranchiseRefreshService")
    def test_refresh_task_returns_stats(self, service_cls, task_cache):
        user = get_user_model().objects.create_user(username="series-task")
        service_cls.return_value.refresh_for_media_ids.return_value = (
            AnimeSeriesViewFranchiseRefreshStats(
                requested=2,
                snapshots_built=1,
                franchise_memberships_created=3,
            )
        )

        result = refresh_anime_series_view_franchise_projection(
            user.id,
            ["10", "2", "2"],
        )

        service_cls.return_value.refresh_for_media_ids.assert_called_once_with(
            user=user,
            media_ids=("2", "10"),
        )
        self.assertEqual(result["media_ids"], ["2", "10"])
        self.assertEqual(result["franchise_memberships_created"], 3)
        task_cache.delete.assert_called_once()

    def test_refresh_task_skips_empty_ids_and_missing_user(self):
        empty = refresh_anime_series_view_franchise_projection(999, [])
        missing = refresh_anime_series_view_franchise_projection(999, ["2"])

        self.assertEqual(empty["reason"], "empty_media_ids")
        self.assertEqual(missing["reason"], "user_not_found")
