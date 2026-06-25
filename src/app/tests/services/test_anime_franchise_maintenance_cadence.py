# ruff: noqa: D101,D102
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from app.services.anime_franchise_maintenance_cadence import (
    compute_success_scan_window,
    summarize_franchise_activity,
)


class AnimeFranchiseMaintenanceCadenceTests(SimpleTestCase):
    def _snapshot(self, *, mal_raw_status="", mal_status="", end_date=None):
        node = SimpleNamespace(
            mal_raw_status=mal_raw_status,
            mal_status=mal_status,
            start_date=date(2000, 1, 1),
            end_date=end_date or date(2001, 1, 1),
        )
        return SimpleNamespace(nodes_by_media_id={"1": node}, is_truncated=False)

    def _window(self, summary):
        return compute_success_scan_window(
            activity_summary=summary,
            state=SimpleNamespace(
                component_root_mal_id="1",
                last_result_fingerprint="fingerprint",
                consecutive_stable_scans=99,
                last_change_at=None,
            ),
            result=SimpleNamespace(
                changed=False,
                root_changed=False,
                component_root_mal_id="1",
                maintenance_fingerprint="fingerprint",
            ),
            now=timezone.now(),
        )

    def test_readable_airing_status_falls_back_to_hot(self):
        snapshot = self._snapshot(mal_status="Currently Airing")
        summary = summarize_franchise_activity(snapshot, now=timezone.now())
        window = self._window(summary)

        self.assertTrue(summary.has_airing)
        self.assertEqual(window.profile, "HOT")
        self.assertEqual(window.reason, "active_or_future")

    def test_readable_upcoming_status_falls_back_to_hot(self):
        snapshot = self._snapshot(mal_status="Upcoming")
        summary = summarize_franchise_activity(snapshot, now=timezone.now())
        window = self._window(summary)

        self.assertTrue(summary.has_upcoming)
        self.assertEqual(window.profile, "HOT")
        self.assertEqual(window.reason, "active_or_future")

    def test_raw_airing_status_still_resolves_to_hot(self):
        snapshot = self._snapshot(mal_raw_status="currently_airing")
        summary = summarize_franchise_activity(snapshot, now=timezone.now())
        window = self._window(summary)

        self.assertTrue(summary.has_airing)
        self.assertEqual(window.profile, "HOT")
        self.assertEqual(window.reason, "active_or_future")
