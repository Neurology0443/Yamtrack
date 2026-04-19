from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import UserMessage, UserMessageLevel
from app.services.anime_franchise_import_service import FranchiseImportStats
from app.tasks import cleanup_user_messages, import_anime_franchise


class CleanupUserMessagesTaskTests(TestCase):
    """Test cleanup of old shown user messages."""

    def setUp(self):
        """Create a user for task tests."""
        self.user = get_user_model().objects.create_user(
            username="test",
        )

    @override_settings(USER_MESSAGE_RETENTION_DAYS=30)
    def test_cleanup_user_messages_deletes_only_old_shown_messages(self):
        """Delete only shown messages older than the retention window."""
        now = timezone.now()
        old_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="old shown",
            shown_at=now - timedelta(days=31),
        )
        recent_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="recent shown",
            shown_at=now - timedelta(days=5),
        )
        unseen = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="unseen",
        )

        deleted_count = cleanup_user_messages()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(UserMessage.objects.filter(id=old_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=recent_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=unseen.id).exists())


class ImportAnimeFranchiseTaskTests(TestCase):
    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_calls_service_with_expected_kwargs(self, mock_service_cls, mock_cache):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.return_value = FranchiseImportStats(
            scanned=4,
            users_considered=3,
            distinct_seeds=2,
            due_selected=2,
            skipped_not_due=1,
            created=6,
            planned_creations=7,
            already_exists=1,
            state_rows_created=1,
            state_rows_updated=1,
            skipped=0,
            errors=0,
            created_ids=["100", "200"],
        )

        result = import_anime_franchise(
            profile_key="satellites",
            full_rescan=True,
            refresh_cache=True,
            limit=10,
            user_ids=[1, 2],
        )

        mock_service_cls.return_value.run.assert_called_once_with(
            profile_key="satellites",
            dry_run=False,
            full_rescan=True,
            limit=10,
            refresh_cache=True,
            user_ids=[1, 2],
        )
        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "scanned": 4,
                "users_considered": 3,
                "distinct_seeds": 2,
                "due_selected": 2,
                "skipped_not_due": 1,
                "created": 6,
                "planned_creations": 7,
                "already_exists": 1,
                "state_rows_created": 1,
                "state_rows_updated": 1,
                "skipped": 0,
                "errors": 0,
                "created_ids": ["100", "200"],
            },
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_skips_when_lock_already_exists(self, mock_service_cls, mock_cache):
        mock_cache.add.return_value = False

        result = import_anime_franchise(profile_key="satellites")

        self.assertEqual(
            result,
            {
                "profile": "satellites",
                "skipped": True,
                "reason": "already_running",
            },
        )
        mock_service_cls.assert_not_called()
        mock_cache.delete.assert_not_called()

    @patch("app.tasks.cache")
    @patch("app.tasks.AnimeFranchiseImportService")
    def test_import_task_releases_lock_when_service_raises(self, mock_service_cls, mock_cache):
        mock_cache.add.return_value = True
        mock_service_cls.return_value.run.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            import_anime_franchise(profile_key="satellites")

        mock_cache.add.assert_called_once_with(
            "anime-franchise-import:satellites",
            "1",
            timeout=60 * 60 * 6,
        )
        mock_cache.delete.assert_called_once_with("anime-franchise-import:satellites")
