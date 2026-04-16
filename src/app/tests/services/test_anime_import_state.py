# ruff: noqa: D101,D102,D107
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Anime, AnimeImportScanState, Item, MediaTypes, Sources, Status
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

    def test_due_selection_respects_due_only_and_limit(self):
        future = timezone.now() + timedelta(days=1)
        continuity_state = AnimeImportScanState.objects.get(
            user=self.user,
            seed_mal_id="100",
            profile_key="continuity",
        )
        continuity_state.next_scan_at = future
        continuity_state.save(update_fields=["next_scan_at", "updated_at"])
        due, skipped = self.service.select_due_seeds(profile_key="continuity", limit=10)
        self.assertEqual(due, [])
        self.assertEqual(skipped, 1)

        due_full, _ = self.service.select_due_seeds(profile_key="continuity", full_rescan=True, limit=1)
        self.assertEqual(len(due_full), 1)

    def test_due_selection_deduplicates_same_user_seed(self):
        Anime.objects.create(
            user=self.user,
            item=self.item,
            status=Status.PLANNING.value,
        )
        due, skipped = self.service.select_due_seeds(profile_key="continuity")
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
