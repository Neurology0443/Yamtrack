# ruff: noqa: D101, D102

from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class RebuildAnimeSeriesViewCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rebuild")

    def test_requires_user_scope(self):
        with self.assertRaisesMessage(CommandError, "Use --user-id or --all-users."):
            call_command("rebuild_anime_series_view")

    @patch(
        "app.management.commands.rebuild_anime_series_view."
        "AnimeSeriesViewProjectionRefreshService.refresh_for_media_ids"
    )
    def test_forwards_media_ids_and_flags(self, refresh):
        refresh.return_value = SimpleNamespace(
            snapshots_refreshed=1,
            memberships_recorded=2,
            memberships_created=2,
            memberships_updated=0,
            memberships_deleted=0,
            errors=0,
        )
        output = StringIO()

        call_command(
            "rebuild_anime_series_view",
            user_ids=[self.user.id],
            media_ids=["10"],
            dry_run=True,
            refresh_cache=True,
            stdout=output,
        )

        refresh.assert_called_once_with(
            user=self.user,
            media_ids={"10"},
            dry_run=True,
            refresh_cache=True,
        )
        self.assertIn("memberships_recorded=2", output.getvalue())
