# ruff: noqa: D101,D102
from unittest.mock import patch

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
