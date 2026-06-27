# ruff: noqa: D101,D102
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import (
    Anime,
    AnimeFranchiseDiscoveredEntry,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from events.notifications import (
    send_franchise_discovery_notification,
    send_user_notification,
)
from events.tasks import (
    scan_mal_anime_release_dates,
    send_entry_added_notification_task,
    send_franchise_discovery_notification_task,
)


class AnimeReleaseDateScanTaskTests(TestCase):
    @override_settings(ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED=False)
    def test_disabled_task_returns_without_calling_service(self):
        result = scan_mal_anime_release_dates()

        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(result["scanned"], 0)

    @override_settings(ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED=True)
    @patch(
        "events.services.anime_release_date_notifications."
        "AnimeReleaseDateNotificationService.scan_due_items",
        return_value={"scanned": 2},
    )
    def test_enabled_task_delegates_to_service(self, mock_scan):
        self.assertEqual(scan_mal_anime_release_dates(), {"scanned": 2})
        mock_scan.assert_called_once_with()


class EntryAddedNotificationTaskTests(TestCase):
    """Tests for the entry-added notification task."""

    def test_task_loads_user_and_calls_notification_helper(self):
        user = get_user_model().objects.create_user(username="task-user")

        with patch(
            "events.tasks.notifications.send_entry_added_notification"
        ) as mock_send:
            send_entry_added_notification_task(user.id, "My Anime")

        mock_send.assert_called_once_with(user, "My Anime")

    def test_task_noops_when_user_missing(self):
        with (
            patch(
                "events.tasks.notifications.send_entry_added_notification"
            ) as mock_send,
            patch("events.tasks.logger.warning") as mock_warning,
        ):
            send_entry_added_notification_task(999999, "My Anime")

        mock_send.assert_not_called()
        mock_warning.assert_called_once_with(
            "Skipping entry-added notification because user %s does not exist",
            999999,
        )


class FranchiseDiscoveryNotificationTaskTests(TestCase):
    """Tests for the franchise discovery notification task."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="franchise-task-user")
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()
        self.discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
        )

    def tearDown(self):
        cache.clear()

    def test_task_does_not_mark_notified_when_preference_disabled(self):
        self.discovery.notification_queued_at = timezone.now()
        self.discovery.save(update_fields=["notification_queued_at"])
        self.user.franchise_discovery_notifications_enabled = False
        self.user.save(update_fields=["franchise_discovery_notifications_enabled"])

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertEqual(result["reason"], "notifications_disabled")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()
        self.assertIsNone(self.discovery.notified_at)
        self.assertEqual(self.discovery.notification_suppressed_reason, "")
        self.assertIsNone(self.discovery.notification_queued_at)

    def test_task_does_not_mark_notified_when_urls_blank(self):
        self.discovery.notification_queued_at = timezone.now()
        self.discovery.save(update_fields=["notification_queued_at"])
        self.user.notification_urls = ""
        self.user.save(update_fields=["notification_urls"])

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertEqual(result["reason"], "notifications_disabled")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()
        self.assertIsNone(self.discovery.notified_at)
        self.assertEqual(self.discovery.notification_suppressed_reason, "")
        self.assertIsNone(self.discovery.notification_queued_at)

    def test_task_does_not_mark_notified_when_send_returns_false(self):
        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification",
            return_value=False,
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertFalse(result["sent"])
        self.assertFalse(result["skipped"])
        self.assertEqual(
            result["discovered_media_id"], self.discovery.discovered_media_id
        )
        self.assertEqual(result["title"], self.discovery.title)
        self.assertEqual(result["root_media_id"], self.discovery.component_root_mal_id)
        self.assertEqual(
            result["component_root_mal_id"],
            self.discovery.component_root_mal_id,
        )
        self.assertEqual(result["reason"], "send_failed")
        mock_send.assert_called_once_with(self.user, self.discovery)
        self.assertIsNone(self.discovery.notified_at)

    def test_task_marks_notified_when_send_returns_true(self):
        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification",
            return_value=True,
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertTrue(result["sent"])
        self.assertFalse(result["skipped"])
        self.assertEqual(result["discovery_id"], self.discovery.id)
        self.assertEqual(
            result["discovered_media_id"], self.discovery.discovered_media_id
        )
        self.assertEqual(result["title"], self.discovery.title)
        self.assertEqual(result["root_media_id"], self.discovery.component_root_mal_id)
        self.assertEqual(
            result["component_root_mal_id"],
            self.discovery.component_root_mal_id,
        )
        self.assertEqual(result["root_title"], self.discovery.root_title)
        self.assertNotIn("reason", result)
        mock_send.assert_called_once_with(self.user, self.discovery)
        self.assertIsNotNone(self.discovery.notified_at)

    def test_task_filters_discovery_by_user(self):
        other_user = get_user_model().objects.create_user(username="other-user")
        other_user.franchise_discovery_notifications_enabled = True
        other_user.notification_urls = "https://example.com/notify"
        other_user.save()

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                other_user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertEqual(result["reason"], "discovery_not_found")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()
        self.assertIsNone(self.discovery.notified_at)

    def test_task_returns_user_not_found_when_user_missing(self):
        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                999999, self.discovery.id
            )

        self.assertEqual(result["reason"], "user_not_found")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()

    def test_task_returns_already_notified_or_suppressed(self):
        self.discovery.notification_suppressed_reason = "already_tracked"
        self.discovery.save(update_fields=["notification_suppressed_reason"])

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.assertEqual(result["reason"], "already_notified_or_suppressed")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        self.assertIsNone(result["notified_at"])
        self.assertEqual(result["notification_suppressed_reason"], "already_tracked")
        mock_send.assert_not_called()

    def test_task_returns_already_notified_when_notified_at_set(self):
        self.discovery.notified_at = timezone.now()
        self.discovery.save(update_fields=["notified_at"])

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.assertEqual(result["reason"], "already_notified_or_suppressed")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        self.assertIsInstance(result["notified_at"], str)
        self.assertIn("T", result["notified_at"])
        self.assertEqual(result["notification_suppressed_reason"], "")
        mock_send.assert_not_called()

    def test_task_suppresses_when_entry_is_tracked_before_send(self):
        item = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Tracked",
            image="https://example.com/img.jpg",
        )
        Anime.objects.create(user=self.user, item=item, status=Status.PLANNING.value)

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.discovery.refresh_from_db()
        self.assertEqual(result["reason"], "already_tracked")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()
        self.assertIsNone(self.discovery.notified_at)
        self.assertEqual(
            self.discovery.notification_suppressed_reason,
            "already_tracked",
        )

    def test_task_returns_already_running_when_lock_exists(self):
        lock_key = f"franchise-discovery-notification:{self.discovery.id}"
        cache.add(lock_key, "1", timeout=300)

        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification"
        ) as mock_send:
            result = send_franchise_discovery_notification_task(
                self.user.id, self.discovery.id
            )

        self.assertEqual(result["reason"], "already_running")
        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        mock_send.assert_not_called()

    def test_cache_lock_is_released_when_send_returns_false(self):
        with patch(
            "events.tasks.notifications.send_franchise_discovery_notification",
            return_value=False,
        ) as mock_send:
            send_franchise_discovery_notification_task(self.user.id, self.discovery.id)
            send_franchise_discovery_notification_task(self.user.id, self.discovery.id)

        self.assertEqual(mock_send.call_count, 2)
        self.assertIsNone(
            cache.get(f"franchise-discovery-notification:{self.discovery.id}")
        )

    def test_cache_lock_is_released_when_send_raises(self):
        with (
            patch(
                "events.tasks.notifications.send_franchise_discovery_notification",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            send_franchise_discovery_notification_task(self.user.id, self.discovery.id)

        self.assertIsNone(
            cache.get(f"franchise-discovery-notification:{self.discovery.id}")
        )


class NotificationHelperReturnValueTests(TestCase):
    """Tests for low-level notification return values."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="notify-helper-user")
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()
        self.discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
        )

    @patch("apprise.Apprise")
    def test_send_user_notification_returns_true_when_apprise_succeeds(
        self, mock_apprise
    ):
        instance = mock_apprise.return_value
        instance.notify.return_value = True

        result = send_user_notification(
            self.user, ["https://example.com/notify"], "Title", "Body"
        )

        self.assertTrue(result)

    @patch("apprise.Apprise")
    def test_send_user_notification_returns_false_when_apprise_fails(
        self, mock_apprise
    ):
        instance = mock_apprise.return_value
        instance.notify.return_value = False

        result = send_user_notification(
            self.user, ["https://example.com/notify"], "Title", "Body"
        )

        self.assertFalse(result)

    @patch("apprise.Apprise")
    def test_send_user_notification_returns_false_on_exception(self, mock_apprise):
        instance = mock_apprise.return_value
        instance.notify.side_effect = RuntimeError("boom")

        result = send_user_notification(
            self.user, ["https://example.com/notify"], "Title", "Body"
        )

        self.assertFalse(result)

    @patch("events.notifications.send_user_notification", return_value=True)
    def test_franchise_discovery_notification_propagates_true(self, _mock_send):
        self.assertTrue(
            send_franchise_discovery_notification(self.user, self.discovery)
        )

    @patch("events.notifications.send_user_notification", return_value=False)
    def test_franchise_discovery_notification_propagates_false(self, _mock_send):
        self.assertFalse(
            send_franchise_discovery_notification(self.user, self.discovery)
        )

    @patch("apprise.Apprise")
    def test_task_leaves_notified_at_empty_when_apprise_fails(self, mock_apprise):
        instance = mock_apprise.return_value
        instance.notify.return_value = False

        send_franchise_discovery_notification_task(self.user.id, self.discovery.id)

        self.discovery.refresh_from_db()
        self.assertIsNone(self.discovery.notified_at)
        self.assertEqual(self.discovery.notification_suppressed_reason, "")
