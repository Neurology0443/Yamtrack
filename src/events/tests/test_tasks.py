from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from events.tasks import send_entry_added_notification_task


class EntryAddedNotificationTaskTests(TestCase):
    """Tests for the entry-added notification task."""

    def test_task_loads_user_and_calls_notification_helper(self):
        user = get_user_model().objects.create_user(username="task-user")

        with patch("events.tasks.notifications.send_entry_added_notification") as mock_send:
            send_entry_added_notification_task(user.id, "My Anime")

        mock_send.assert_called_once_with(user, "My Anime")

    def test_task_noops_when_user_missing(self):
        with (
            patch("events.tasks.notifications.send_entry_added_notification") as mock_send,
            patch("events.tasks.logger.warning") as mock_warning,
        ):
            send_entry_added_notification_task(999999, "My Anime")

        mock_send.assert_not_called()
        mock_warning.assert_called_once_with(
            "Skipping entry-added notification because user %s does not exist",
            999999,
        )
