# ruff: noqa: D101,D102
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import mal_cache
from events.models import (
    AnimeReleaseDateNotificationDelivery,
    AnimeReleaseDateScanState,
    AnimeStartDatePrecision,
)
from events.services.anime_release_date_notifications import (
    AnimeReleaseDateNotificationService,
    is_mal_cache_recent_for_release_date_scan,
    parse_mal_start_date,
)


class ParseMALStartDateTests(TestCase):
    def test_accepts_supported_precisions(self):
        year = parse_mal_start_date("2027")
        month = parse_mal_start_date("2027-05")
        day = parse_mal_start_date("2027-05-27")

        self.assertEqual(year.precision, AnimeStartDatePrecision.YEAR)
        self.assertEqual(month.precision, AnimeStartDatePrecision.MONTH)
        self.assertEqual(day.precision, AnimeStartDatePrecision.DAY)
        self.assertEqual(day.date_value.isoformat(), "2027-05-27")

    def test_rejects_empty_loose_and_invalid_dates(self):
        for value in (None, "", "2027-5", "2027-13", "2027-02-31", "abc"):
            with self.subTest(value=value):
                self.assertIsNone(parse_mal_start_date(value))

    def test_cache_freshness_uses_release_date_window(self):
        recent = {"fetched_at": timezone.now().isoformat()}
        stale = {
            "fetched_at": (timezone.now() - timedelta(hours=25)).isoformat(),
        }

        self.assertTrue(
            is_mal_cache_recent_for_release_date_scan(
                recent,
                max_age_hours=24,
            ),
        )
        self.assertFalse(
            is_mal_cache_recent_for_release_date_scan(
                stale,
                max_age_hours=24,
            ),
        )


@override_settings(
    ANIME_RELEASE_DATE_SCAN_BATCH_SIZE=25,
    ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS=24,
    ANIME_RELEASE_DATE_SCAN_ERROR_RETRY_HOURS=12,
    ANIME_RELEASE_DATE_SCAN_MAX_BACKOFF_DAYS=7,
    ANIME_RELEASE_DATE_SCAN_LOCK_MINUTES=360,
)
class AnimeReleaseDateNotificationServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="release-date-user",
            notification_urls="json://localhost",
            anime_release_date_notifications_enabled=True,
        )
        self.item = Item.objects.create(
            media_id="100",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Future Anime",
            image="https://example.com/anime.jpg",
        )
        Anime.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )
        self.service = AnimeReleaseDateNotificationService()

    @staticmethod
    def metadata(start_date, status="Upcoming"):
        return {
            "media_id": "100",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Future Anime",
            "image": "https://example.com/anime.jpg",
            "details": {
                "start_date": start_date,
                "status": status,
            },
        }

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch(
        "events.services.anime_release_date_notifications.send_user_notification",
    )
    def test_first_observation_initializes_silently(self, mock_send, _mock_jitter):
        result = self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=None,
            new_metadata=self.metadata("2027"),
            source="metadata_refresh",
        )

        state = AnimeReleaseDateScanState.objects.get(item=self.item)
        self.assertEqual(state.last_seen_start_date_text, "2027")
        self.assertEqual(state.last_seen_start_date_precision, "year")
        self.assertEqual(result["initialized"], 1)
        self.assertFalse(
            AnimeReleaseDateNotificationDelivery.objects.exists(),
        )
        mock_send.assert_not_called()

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch(
        "events.services.anime_release_date_notifications.send_user_notification",
        return_value=True,
    )
    def test_year_becoming_month_sends_one_updated_delivery(
        self,
        mock_send,
        _mock_jitter,
    ):
        result = self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata("2027"),
            new_metadata=self.metadata("2027-05"),
            source="metadata_refresh",
        )

        delivery = AnimeReleaseDateNotificationDelivery.objects.get()
        self.assertEqual(delivery.previous_start_date_text, "2027")
        self.assertEqual(delivery.start_date_text, "2027-05")
        self.assertEqual(delivery.change_kind, "updated")
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["notifications_sent"], 1)
        mock_send.assert_called_once()

        duplicate = self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata("2027"),
            new_metadata=self.metadata("2027-05"),
            source="metadata_refresh",
        )
        self.assertEqual(duplicate["notifications_sent"], 0)
        self.assertEqual(
            AnimeReleaseDateNotificationDelivery.objects.count(),
            1,
        )

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch(
        "events.services.anime_release_date_notifications.send_user_notification",
        return_value=True,
    )
    def test_missing_date_becoming_year_is_announced(
        self,
        _mock_send,
        _mock_jitter,
    ):
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=None,
            new_metadata=self.metadata(None),
            source="metadata_refresh",
        )

        result = self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata(None),
            new_metadata=self.metadata("2027"),
            source="metadata_refresh",
        )

        delivery = AnimeReleaseDateNotificationDelivery.objects.get()
        self.assertEqual(delivery.change_kind, "announced")
        self.assertEqual(result["announced"], 1)

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch(
        "events.services.anime_release_date_notifications.send_user_notification",
        return_value=True,
    )
    def test_full_date_change_and_reverse_transition_are_distinct(
        self,
        _mock_send,
        _mock_jitter,
    ):
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=None,
            new_metadata=self.metadata("2027-05-27"),
            source="metadata_refresh",
        )
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata("2027-05-27"),
            new_metadata=self.metadata("2027-06-03"),
            source="metadata_refresh",
        )
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata("2027-06-03"),
            new_metadata=self.metadata("2027-05-27"),
            source="metadata_refresh",
        )

        transitions = set(
            AnimeReleaseDateNotificationDelivery.objects.values_list(
                "previous_start_date_text",
                "start_date_text",
            ),
        )
        self.assertEqual(
            transitions,
            {
                ("2027-05-27", "2027-06-03"),
                ("2027-06-03", "2027-05-27"),
            },
        )

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch(
        "events.services.anime_release_date_notifications.send_user_notification",
    )
    def test_invalid_date_does_not_clear_last_valid_date(
        self,
        mock_send,
        _mock_jitter,
    ):
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=None,
            new_metadata=self.metadata("2027-05"),
            source="metadata_refresh",
        )
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=self.metadata("2027-05"),
            new_metadata=self.metadata("2027-13"),
            source="metadata_refresh",
        )

        state = AnimeReleaseDateScanState.objects.get(item=self.item)
        self.assertEqual(state.last_seen_start_date_text, "2027-05")
        self.assertEqual(state.last_seen_raw_start_date, "2027-13")
        mock_send.assert_not_called()

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    @patch("events.services.anime_release_date_notifications.mal.anime")
    def test_scan_uses_recent_cache_without_calling_mal(
        self,
        mock_anime,
        _mock_jitter,
    ):
        mal_cache.save_anime_cache(
            self.item.media_id,
            self.metadata("2027"),
            fetched_at=timezone.now(),
        )

        result = self.service.scan_due_items()

        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["initialized"], 1)
        mock_anime.assert_not_called()

    def test_scan_refreshes_stale_cache_once_for_shared_item(
        self,
    ):
        other_user = get_user_model().objects.create_user(
            username="other-release-date-user",
            notification_urls="json://localhost",
            anime_release_date_notifications_enabled=True,
        )
        Anime.objects.bulk_create(
            [
                Anime(
                    user=other_user,
                    item=self.item,
                    status=Status.IN_PROGRESS.value,
                ),
            ],
        )
        mal_cache.save_anime_cache(
            self.item.media_id,
            self.metadata(None),
            fetched_at=timezone.now() - timedelta(days=2),
        )
        with (
            patch.object(
                AnimeReleaseDateNotificationService,
                "_jitter",
                return_value=0,
            ),
            patch(
                "events.services.anime_release_date_notifications.mal.anime",
                return_value=self.metadata("2027"),
            ) as mock_anime,
        ):
            result = self.service.scan_due_items()

        self.assertEqual(result["scanned"], 1)
        mock_anime.assert_called_once_with(
            self.item.media_id,
            refresh_cache=True,
        )

    def test_ineligible_or_excluded_tracking_is_not_selected(self):
        self.user.notification_excluded_items.add(self.item)
        self.assertEqual(self.service._eligible_item_ids(), [])

        self.user.notification_excluded_items.remove(self.item)
        Anime.objects.filter(user=self.user, item=self.item).update(
            status=Status.COMPLETED.value,
        )
        self.assertEqual(self.service._eligible_item_ids(), [])

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    def test_past_date_initializes_silently_and_disables_state(self, _mock_jitter):
        self.service.process_metadata_refresh(
            media_id=self.item.media_id,
            old_metadata=None,
            new_metadata=self.metadata("2020-01-01"),
            source="metadata_refresh",
        )

        state = AnimeReleaseDateScanState.objects.get(item=self.item)
        self.assertTrue(state.disabled)
        self.assertFalse(
            AnimeReleaseDateNotificationDelivery.objects.exists(),
        )

    @patch("events.services.anime_release_date_notifications.mal.anime")
    def test_scan_disables_complete_date_once_it_has_passed(self, mock_anime):
        AnimeReleaseDateScanState.objects.create(
            item=self.item,
            initialized_at=timezone.now() - timedelta(days=30),
            last_seen_start_date_text="2020-01-01",
            last_seen_start_date_precision=AnimeStartDatePrecision.DAY,
            last_seen_start_date=timezone.localdate() - timedelta(days=1),
            next_scan_at=timezone.now() - timedelta(hours=1),
        )

        result = self.service.scan_due_items()

        state = AnimeReleaseDateScanState.objects.get(item=self.item)
        self.assertTrue(state.disabled)
        self.assertEqual(result["scanned"], 0)
        mock_anime.assert_not_called()

    @patch.object(AnimeReleaseDateNotificationService, "_jitter", return_value=0)
    def test_import_initializes_state_without_eligible_user(self, _mock_jitter):
        self.user.anime_release_date_notifications_enabled = False
        self.user.save(
            update_fields=["anime_release_date_notifications_enabled"],
        )

        self.service.initialize_or_prioritize_imported_item(
            item=self.item,
            metadata=self.metadata("2027-05", status="Upcoming"),
        )

        state = AnimeReleaseDateScanState.objects.get(item=self.item)
        self.assertEqual(state.last_seen_start_date_text, "2027-05")
        self.assertEqual(state.last_seen_mal_status, "Upcoming")
        self.assertFalse(
            AnimeReleaseDateNotificationDelivery.objects.exists(),
        )
