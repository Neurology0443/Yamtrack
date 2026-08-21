# ruff: noqa: D101, D102

from dataclasses import FrozenInstanceError
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from anime.metadata import AnimeMetadataUnavailable, InvalidAnimeMetadataPayload
from anime.models import AnimeMetadataRecord
from anime.store import MalAnimeMetadataStore
from anime.use_cases import GetAnimeMetadata, RefreshAnimeMetadata


def mal_payload():
    """Return representative raw MAL anime metadata."""
    return {
        "title": "Fullmetal Alchemist: Brotherhood",
        "alternative_titles": {"en": "Fullmetal Alchemist Brotherhood"},
        "main_picture": {
            "medium": "https://img/medium.jpg",
            "large": "https://img/large.jpg",
        },
        "media_type": "tv",
        "start_date": "2009-04",
        "end_date": "2010-07-04",
        "synopsis": "Two brothers search for a philosopher's stone.",
        "status": "finished_airing",
        "genres": [{"id": 1, "name": "Action"}],
        "mean": 9.1,
        "num_scoring_users": 2100000,
        "num_episodes": 64,
        "average_episode_duration": 1440,
        "studios": [{"id": 4, "name": "Bones"}],
        "start_season": {"year": 2009, "season": "spring"},
        "broadcast": {"day_of_the_week": "sunday", "start_time": "17:00"},
        "source": "manga",
        "related_anime": [{"node": {"id": 121}, "relation_type": "prequel"}],
        "recommendations": [{"node": {"id": 9253}, "num_recommendations": 42}],
    }


class AnimeMetadataTestCase(TestCase):
    def setUp(self):
        now = timezone.now()
        self.record = AnimeMetadataRecord.objects.create(
            media_id=1,
            canonical_title="Persisted title",
            genres=["Action"],
            studios=["Bones"],
            relations=[{"media_id": 2, "relation_type": "sequel"}],
            recommendations=[{"media_id": 3, "count": 4}],
            fetched_at=now,
            refresh_after=now + timedelta(hours=24),
        )

    def test_refresh_normalizes_and_persists_complete_payload(self):
        store = MalAnimeMetadataStore()
        with patch.object(store, "_fetch_provider_payload", return_value=mal_payload()):
            snapshot = store.refresh(5114)

        record = AnimeMetadataRecord.objects.get(media_id=5114)
        self.assertEqual(snapshot.genres, ("Action",))
        self.assertEqual(snapshot.runtime, 1440)
        self.assertEqual(snapshot.start_date, "2009-04")
        self.assertEqual(snapshot.relations[0].relation_type, "prequel")
        self.assertEqual(snapshot.recommendations[0].count, 42)
        self.assertEqual(record.refresh_after, record.fetched_at + timedelta(hours=24))
        with self.assertRaises(FrozenInstanceError):
            snapshot.canonical_title = "Changed"

    def test_normalization_preserves_optional_absence_and_date_precision(self):
        payload = mal_payload()
        payload.update(
            alternative_titles={},
            main_picture=None,
            synopsis="",
            num_episodes=0,
            average_episode_duration=0,
            start_date="2026",
            end_date="2026-08",
        )
        store = MalAnimeMetadataStore()
        with patch.object(store, "_fetch_provider_payload", return_value=payload):
            snapshot = store.refresh(2)

        self.assertIsNone(snapshot.alternative_title_en)
        self.assertIsNone(snapshot.image)
        self.assertIsNone(snapshot.synopsis)
        self.assertIsNone(snapshot.episode_count)
        self.assertIsNone(snapshot.runtime)
        self.assertEqual((snapshot.start_date, snapshot.end_date), ("2026", "2026-08"))

    def test_invalid_ids_do_not_touch_database_provider_or_queue(self):
        for media_id in (0, -1, True, False, "1", None):
            store = Mock(spec=MalAnimeMetadataStore)
            enqueue = Mock()
            with (
                self.subTest(media_id=media_id),
                self.assertRaisesRegex(
                    ValueError, "media_id must be a positive integer"
                ),
            ):
                GetAnimeMetadata(store=store, enqueue_refresh=enqueue).execute(media_id)
            store.get_record.assert_not_called()
            store.refresh.assert_not_called()
            enqueue.assert_not_called()

        self.assertEqual(AnimeMetadataRecord.objects.count(), 1)

    def test_refresh_entry_points_validate_ids_before_store_or_provider(self):
        for media_id in (0, -1, True, False, "1", None):
            store = Mock(spec=MalAnimeMetadataStore)
            with self.subTest(use_case_id=media_id), self.assertRaises(ValueError):
                RefreshAnimeMetadata(store).execute(media_id)
            store.refresh.assert_not_called()

            real_store = MalAnimeMetadataStore()
            with patch.object(real_store, "_fetch_provider_payload") as fetch:
                with self.subTest(store_id=media_id), self.assertRaises(ValueError):
                    real_store.refresh(media_id)
                fetch.assert_not_called()
        self.assertEqual(AnimeMetadataRecord.objects.count(), 1)

    def test_fresh_read_does_not_refresh_claim_or_enqueue(self):
        store = Mock(wraps=MalAnimeMetadataStore())
        enqueue = Mock()
        snapshot = GetAnimeMetadata(store, enqueue).execute(self.record.media_id)
        self.assertEqual(snapshot.canonical_title, "Persisted title")
        store.refresh.assert_not_called()
        store.claim_async_refresh.assert_not_called()
        enqueue.assert_not_called()

    def test_stale_read_claims_only_one_enqueue(self):
        AnimeMetadataRecord.objects.filter(pk=self.record.pk).update(
            refresh_after=timezone.now() - timedelta(seconds=1),
            last_refresh_attempt_at=None,
        )
        enqueue = Mock()
        use_case = GetAnimeMetadata(enqueue_refresh=enqueue)
        first = use_case.execute(self.record.media_id)
        second = use_case.execute(self.record.media_id)
        self.assertEqual(first, second)
        enqueue.assert_called_once_with(self.record.media_id)

    def test_stale_read_during_error_cooldown_does_not_enqueue(self):
        AnimeMetadataRecord.objects.filter(pk=self.record.pk).update(
            refresh_after=timezone.now() - timedelta(seconds=1),
            last_refresh_attempt_at=timezone.now() - timedelta(minutes=10),
            last_refresh_error_at=timezone.now(),
        )
        enqueue = Mock()
        snapshot = GetAnimeMetadata(enqueue_refresh=enqueue).execute(
            self.record.media_id
        )
        self.assertEqual(snapshot.canonical_title, self.record.canonical_title)
        enqueue.assert_not_called()

    def test_enqueue_failure_does_not_break_or_change_stale_read(self):
        stale_at = timezone.now() - timedelta(seconds=1)
        AnimeMetadataRecord.objects.filter(pk=self.record.pk).update(
            refresh_after=stale_at,
            last_refresh_attempt_at=None,
        )
        enqueue = Mock(side_effect=ConnectionError)
        snapshot = GetAnimeMetadata(enqueue_refresh=enqueue).execute(
            self.record.media_id
        )
        self.record.refresh_from_db()
        self.assertEqual(snapshot.canonical_title, self.record.canonical_title)
        self.assertEqual(self.record.refresh_after, stale_at)

    def test_expected_provider_failure_preserves_last_known_good(self):
        original = MalAnimeMetadataStore().to_snapshot(self.record)
        store = MalAnimeMetadataStore()
        error = requests.exceptions.Timeout("timed out")
        with (
            patch.object(store, "_fetch_provider_payload", side_effect=error),
            self.assertRaises(AnimeMetadataUnavailable),
        ):
            store.refresh(self.record.media_id)
        self.record.refresh_from_db()
        self.assertEqual(MalAnimeMetadataStore().to_snapshot(self.record), original)
        self.assertIn("Timeout", self.record.last_error_message)

    def test_invalid_payload_failure_preserves_last_known_good(self):
        original = MalAnimeMetadataStore().to_snapshot(self.record)
        store = MalAnimeMetadataStore()
        with (
            patch.object(store, "_fetch_provider_payload", return_value={}),
            self.assertRaises(AnimeMetadataUnavailable),
        ):
            store.refresh(self.record.media_id)
        self.record.refresh_from_db()
        self.assertEqual(MalAnimeMetadataStore().to_snapshot(self.record), original)
        self.assertIn("title", self.record.last_error_message)

    def test_first_failure_cooldown_expires_and_allows_retry(self):
        store = MalAnimeMetadataStore()
        error = requests.exceptions.Timeout("timed out")
        with patch.object(store, "_fetch_provider_payload", side_effect=error) as fetch:
            with self.assertRaises(AnimeMetadataUnavailable):
                GetAnimeMetadata(store).execute(7)
            with self.assertRaises(AnimeMetadataUnavailable):
                GetAnimeMetadata(store).execute(7)
            self.assertEqual(fetch.call_count, 1)

        AnimeMetadataRecord.objects.filter(media_id=7).update(
            last_refresh_error_at=timezone.now() - timedelta(hours=2)
        )
        with patch.object(store, "_fetch_provider_payload", return_value=mal_payload()):
            snapshot = GetAnimeMetadata(store).execute(7)
        self.assertEqual(snapshot.media_id, 7)

    def test_unexpected_persistence_bug_is_not_converted(self):
        store = MalAnimeMetadataStore()
        with (
            patch.object(store, "_fetch_provider_payload", return_value=mal_payload()),
            patch.object(
                AnimeMetadataRecord.objects,
                "update_or_create",
                side_effect=RuntimeError("database bug"),
            ),
            self.assertRaisesRegex(RuntimeError, "database bug"),
        ):
            store.refresh(8)
        self.assertFalse(AnimeMetadataRecord.objects.filter(media_id=8).exists())

    def test_invalid_payload_errors_name_the_field(self):
        cases = (
            ({"title": None}, "title"),
            (
                {"related_anime": [{"node": {}, "relation_type": "sequel"}]},
                "related_anime[0].node.id",
            ),
            (
                {"related_anime": [{"node": {"id": 2}}]},
                "related_anime[0].relation_type",
            ),
            (
                {"recommendations": [{"node": {"id": 0}, "num_recommendations": 1}]},
                "recommendations[0].node.id",
            ),
            ({"genres": {}}, "genres"),
            ({"studios": {}}, "studios"),
        )
        store = MalAnimeMetadataStore()
        for changes, field in cases:
            payload = mal_payload()
            payload.update(changes)
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    InvalidAnimeMetadataPayload,
                    field.replace("[", r"\[").replace("]", r"\]"),
                ),
            ):
                store._normalize(1, payload)

    def test_refresh_after_freshness_and_database_constraint(self):
        store = MalAnimeMetadataStore()
        self.assertFalse(store.refresh_is_due(self.record, now=timezone.now()))
        self.record.refresh_after = timezone.now() - timedelta(seconds=1)
        self.assertTrue(store.refresh_is_due(self.record, now=timezone.now()))
        self.record.refresh_after = None
        with self.assertRaisesRegex(ValueError, "requires refresh_after"):
            store.refresh_is_due(self.record, now=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnimeMetadataRecord.objects.create(
                media_id=99,
                canonical_title="Invalid",
                fetched_at=timezone.now(),
                refresh_after=None,
            )

    def test_two_successful_refreshes_update_one_row_and_clear_error(self):
        old_pk = self.record.pk
        AnimeMetadataRecord.objects.filter(pk=old_pk).update(
            last_refresh_error_at=timezone.now(), last_error_message="old"
        )
        store = MalAnimeMetadataStore()
        with patch.object(store, "_fetch_provider_payload", return_value=mal_payload()):
            first = store.refresh(self.record.media_id)
            second = store.refresh(self.record.media_id)
        record = AnimeMetadataRecord.objects.get(pk=old_pk)
        self.assertEqual(first.media_id, second.media_id)
        self.assertEqual(AnimeMetadataRecord.objects.filter(media_id=1).count(), 1)
        self.assertEqual(record.refresh_after, record.fetched_at + timedelta(hours=24))
        self.assertIsNone(record.last_refresh_error_at)
        self.assertIsNone(record.last_error_message)
