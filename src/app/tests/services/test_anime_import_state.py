# ruff: noqa: D101,D102,D107
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Anime, AnimeImportScanState, Item, MediaTypes, Sources, Status
from app.services.anime_franchise_import_profiles import (
    ContinuityImportProfile,
    SatellitesImportProfile,
)
from app.services.anime_import_state import AnimeImportStateService


class AnimeImportStateServiceTests(TestCase):
    def setUp(self):
        self.mock_metadata = {
            "max_progress": 12,
            "details": {"episodes": 12},
        }
        self.metadata_patcher = patch(
            "app.providers.services.get_media_metadata",
            return_value=self.mock_metadata,
        )
        self.metadata_patcher.start()
        self.addCleanup(self.metadata_patcher.stop)

        self.user = get_user_model().objects.create_user(username="state", password="pwd")
        self.item = Item.objects.create(
            media_id="100",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Seed",
            image="https://example.com/100.jpg",
        )
        Anime.objects.create(user=self.user, item=self.item, status=Status.IN_PROGRESS.value)
        self.service = AnimeImportStateService()
        self.continuity_profile = ContinuityImportProfile()

    def test_due_selection_respects_due_only_and_limit(self):
        future = timezone.now() + timedelta(days=1)
        continuity_state = AnimeImportScanState.objects.get(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
        )
        continuity_state.next_scan_at = future
        continuity_state.save(update_fields=["next_scan_at", "updated_at"])
        due, skipped = self.service.select_due_seeds(
            profile=self.continuity_profile,
            profile_key="continuity",
            limit=10,
        )
        self.assertEqual(due, [])
        self.assertEqual(skipped, 1)

        due_full, _ = self.service.select_due_seeds(
            profile=self.continuity_profile,
            profile_key="continuity",
            full_rescan=True,
            limit=1,
        )
        self.assertEqual(len(due_full), 1)

    def test_due_selection_deduplicates_same_user_seed(self):
        Anime.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )
        due, skipped = self.service.select_due_seeds(
            profile=self.continuity_profile,
            profile_key="continuity",
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].user_id, self.user.id)
        self.assertEqual(due[0].seed_mal_id, "100")

    def test_fingerprint_and_success_backoff_and_error_retry(self):
        fingerprint = self.service.build_fingerprint("continuity", {"ids": ["100"]})
        state, _, changed = self.service.record_success(
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
            fingerprint=fingerprint,
            component_root_mal_id="100",
            component_size=1,
        )
        self.assertTrue(changed)
        self.assertGreater(state.next_scan_at, timezone.now())

        error_state, _ = self.service.record_error(
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
        )
        self.assertEqual(error_state.consecutive_error_count, 1)

    def test_hot_priority_due_now(self):
        future = timezone.now() + timedelta(days=10)
        continuity_state = AnimeImportScanState.objects.get(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
        )
        continuity_state.next_scan_at = future
        continuity_state.save(update_fields=["next_scan_at", "updated_at"])
        updated = self.service.mark_due_now(user_id=self.user.id, seed_mal_id="100")
        self.assertEqual(updated, 3)
        self.assertEqual(
            AnimeImportScanState.objects.filter(
                user=self.user,
                seed_mal_id="100",
            ).count(),
            3,
        )
        refreshed_continuity_state = AnimeImportScanState.objects.get(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
        )
        self.assertLess(refreshed_continuity_state.next_scan_at, future)

    def test_satellites_profile_selects_only_canonical_roots_as_seeds(self):
        satellite_item = Item.objects.create(
            media_id="200",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Satellite",
            image="https://example.com/200.jpg",
        )
        Anime.objects.create(
            user=self.user,
            item=satellite_item,
            status=Status.PLANNING.value,
        )
        AnimeImportScanState.objects.update_or_create(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
            defaults={"component_root_mal_id": "100", "next_scan_at": timezone.now()},
        )
        AnimeImportScanState.objects.update_or_create(
            user=self.user,
            seed_mal_id="200",
            profile_key="continuity",
            defaults={"component_root_mal_id": "100", "next_scan_at": timezone.now()},
        )

        due, skipped = self.service.select_due_seeds(
            profile=SatellitesImportProfile(),
            profile_key="satellites",
        )
        self.assertEqual(skipped, 0)
        self.assertEqual([(seed.user_id, seed.seed_mal_id) for seed in due], [(self.user.id, "100")])

    def test_continuity_profile_remains_all_library_seedable(self):
        satellite_item = Item.objects.create(
            media_id="200",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Satellite",
            image="https://example.com/200.jpg",
        )
        Anime.objects.create(
            user=self.user,
            item=satellite_item,
            status=Status.PLANNING.value,
        )
        AnimeImportScanState.objects.update_or_create(
            user=self.user,
            seed_mal_id="200",
            profile_key="continuity",
            defaults={"component_root_mal_id": "100", "next_scan_at": timezone.now()},
        )

        due, skipped = self.service.select_due_seeds(
            profile=self.continuity_profile,
            profile_key="continuity",
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(
            [(seed.user_id, seed.seed_mal_id) for seed in due],
            [(self.user.id, "100"), (self.user.id, "200")],
        )

    def test_stable_delay_keeps_short_window_below_48_hours(self):
        delay = self.service._stable_delay(
            hours=12,
            stable_count=0,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
        )
        self.assertGreaterEqual(delay, timedelta(hours=12))
        self.assertLessEqual(delay, timedelta(hours=12, minutes=30))

    def test_stable_delay_uses_expanded_window_for_long_delays(self):
        delay = self.service._stable_delay(
            hours=12,
            stable_count=4,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
        )
        self.assertGreaterEqual(delay, timedelta(hours=192))
        self.assertLessEqual(delay, timedelta(hours=192, minutes=1152))

    def test_stable_jitter_window_threshold_values(self):
        self.assertEqual(self.service._stable_jitter_window_minutes(47), 30)
        self.assertEqual(self.service._stable_jitter_window_minutes(48), 288)

    def test_jittered_delay_is_deterministic(self):
        delay_a = self.service._jittered_delay(
            hours=192,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
            jitter_window_minutes=1152,
        )
        delay_b = self.service._jittered_delay(
            hours=192,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
            jitter_window_minutes=1152,
        )
        self.assertEqual(delay_a, delay_b)

    def test_jittered_delay_is_profile_specific(self):
        continuity_delay = self.service._jittered_delay(
            hours=96,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
            jitter_window_minutes=576,
        )
        satellites_delay = self.service._jittered_delay(
            hours=96,
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="satellites",
            jitter_window_minutes=576,
        )
        self.assertNotEqual(continuity_delay, satellites_delay)

    def test_record_success_changed_result_keeps_short_behavior(self):
        fingerprint = self.service.build_fingerprint("continuity", {"ids": ["100"]})
        state, _, changed = self.service.record_success(
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
            fingerprint=fingerprint,
            component_root_mal_id="100",
            component_size=1,
        )
        self.assertTrue(changed)
        delay = state.next_scan_at - state.last_success_at
        self.assertGreaterEqual(delay, timedelta(hours=6))
        self.assertLessEqual(delay, timedelta(hours=6, minutes=30))

    def test_record_error_stays_short_window(self):
        state, _ = self.service.record_error(
            user_id=self.user.id,
            seed_mal_id="100",
            profile_key="continuity",
        )
        self.assertEqual(state.consecutive_error_count, 1)
        delay = state.next_scan_at - state.last_error_at
        self.assertGreaterEqual(delay, timedelta(hours=2))
        self.assertLessEqual(delay, timedelta(hours=2, minutes=30))
