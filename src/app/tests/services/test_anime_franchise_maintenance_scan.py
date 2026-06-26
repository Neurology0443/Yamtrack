# ruff: noqa: D101,D102
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import AnimeFranchiseMaintenanceScanState
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceResult
from app.services.anime_franchise_maintenance_scan import (
    AnimeFranchiseMaintenanceScanService,
)


class AnimeFranchiseMaintenanceScanServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scan-user")
        self.service = AnimeFranchiseMaintenanceScanService(
            maintenance_service=object()
        )
        self.now = timezone.now()

    def _state(self, seed_mal_id="457", *, stable_scans=3):
        return AnimeFranchiseMaintenanceScanState.objects.create(
            user=self.user,
            seed_mal_id=seed_mal_id,
            component_root_mal_id="457",
            next_scan_at=self.now,
            last_result_fingerprint="fingerprint",
            consecutive_stable_scans=stable_scans,
        )

    def _result(self, tracked_member_media_ids):
        return AnimeFranchiseMaintenanceResult(
            user_id=self.user.id,
            seed_mal_id="457",
            component_root_mal_id="457",
            maintenance_fingerprint="fingerprint",
            tracked_member_media_ids=tuple(tracked_member_media_ids),
        )

    def test_cover_tracked_member_states_skips_processed_seed(self):
        state = self._state(stable_scans=3)
        result = self._result(("457",))

        self.service._mark_success(state, result=result, now=self.now)
        state.refresh_from_db()
        next_scan_at = state.next_scan_at
        self.assertEqual(state.consecutive_stable_scans, 4)

        with patch.object(
            self.service,
            "_tracked_seed_ids_for_user",
            return_value={"457"},
        ):
            self.service._cover_tracked_member_states(
                state, result=result, now=self.now
            )

        state.refresh_from_db()
        self.assertEqual(state.consecutive_stable_scans, 4)
        self.assertEqual(state.next_scan_at, next_scan_at)
        self.assertEqual(
            AnimeFranchiseMaintenanceScanState.objects.filter(
                user=self.user,
                seed_mal_id="457",
            ).count(),
            1,
        )

    def test_cover_tracked_member_states_covers_other_members_only(self):
        state = self._state(stable_scans=3)
        result = self._result(("457", "458"))

        self.service._mark_success(state, result=result, now=self.now)
        state.refresh_from_db()
        next_scan_at = state.next_scan_at
        self.assertEqual(state.consecutive_stable_scans, 4)

        with patch.object(
            self.service,
            "_tracked_seed_ids_for_user",
            return_value={"457", "458"},
        ):
            self.service._cover_tracked_member_states(
                state, result=result, now=self.now
            )

        state.refresh_from_db()
        member_state = AnimeFranchiseMaintenanceScanState.objects.get(
            user=self.user,
            seed_mal_id="458",
        )
        self.assertNotEqual(member_state.pk, state.pk)
        self.assertEqual(state.consecutive_stable_scans, 4)
        self.assertEqual(state.next_scan_at, next_scan_at)
        self.assertEqual(member_state.component_root_mal_id, "457")
        self.assertEqual(member_state.last_result_fingerprint, "fingerprint")
        self.assertEqual(member_state.consecutive_stable_scans, 1)

    def test_scan_due_does_not_self_cover_processed_seed(self):
        state = self._state(stable_scans=8)
        result = self._result(("457",))
        result.cache_built = True
        result.discovery_processed = True
        maintenance_service = Mock()
        maintenance_service.process_seed.return_value = result
        service = AnimeFranchiseMaintenanceScanService(
            maintenance_service=maintenance_service
        )

        with patch.object(service, "_is_seed_tracked", return_value=True):
            stats = service.scan_due(limit=1)

        state.refresh_from_db()
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.succeeded, 1)
        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.skipped_duplicate_root, 0)
        maintenance_service.process_seed.assert_called_once()
        self.assertEqual(state.consecutive_stable_scans, 9)
        self.assertEqual(state.last_error, "")
        self.assertGreater(state.next_scan_at, self.now)

    def test_cover_tracked_member_states_does_not_mutate_processed_result_window(self):
        state = self._state(stable_scans=3)
        result = self._result(("457", "458"))
        AnimeFranchiseMaintenanceScanState.objects.create(
            user=self.user,
            seed_mal_id="458",
            component_root_mal_id="457",
            next_scan_at=self.now,
            last_result_fingerprint="old-fingerprint",
            consecutive_stable_scans=5,
        )

        self.service._mark_success(state, result=result, now=self.now)
        original_scan_window = result.scan_window
        original_cadence_profile = result.cadence_profile
        original_cadence_reason = result.cadence_reason

        with patch.object(
            self.service,
            "_tracked_seed_ids_for_user",
            return_value={"457", "458"},
        ):
            self.service._cover_tracked_member_states(
                state, result=result, now=self.now
            )

        member_state = AnimeFranchiseMaintenanceScanState.objects.get(
            user=self.user,
            seed_mal_id="458",
        )
        self.assertGreater(member_state.next_scan_at, self.now)
        self.assertEqual(member_state.last_result_fingerprint, "fingerprint")
        self.assertIs(result.scan_window, original_scan_window)
        self.assertEqual(result.cadence_profile, original_cadence_profile)
        self.assertEqual(result.cadence_reason, original_cadence_reason)
