# ruff: noqa: D101,D102,D107,S106,ARG002
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    Anime,
    AnimeFranchiseDiscoveredEntry,
    AnimeFranchiseDiscoveryState,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_franchise_discovery import (
    DISCOVERY_NOTIFICATION_REACTIVATION_WINDOW,
    DISCOVERY_NOTIFICATION_RETRY_AFTER,
    AnimeFranchiseDiscoveryProjection,
    AnimeFranchiseDiscoveryService,
    FranchiseDiscoveryCandidate,
)
from app.services.anime_tracking import bulk_mal_anime_tracked_ids


class FakeProjection(AnimeFranchiseDiscoveryProjection):
    def __init__(self, candidates):
        self.candidates = candidates

    def project(self, snapshot):
        return self.candidates


class AnimeFranchiseDiscoveryServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.snapshot = SimpleNamespace()

    def service(self, candidates):
        return AnimeFranchiseDiscoveryService(projection=FakeProjection(candidates))

    def candidate(self, media_id="2", section_key="specials", anime_media_type="ova"):
        return FranchiseDiscoveryCandidate(
            media_id=media_id,
            title=f"Anime {media_id}",
            section_key=section_key,
            section_label="Specials",
            relation_type="side_story",
            source_media_id="1",
            anime_media_type=anime_media_type,
            root_title="Root",
        )

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_first_scan_creates_baseline_without_notification(self, mock_notify):
        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        state = AnimeFranchiseDiscoveryState.objects.get(user=self.user)
        self.assertIsNotNone(state.baseline_completed_at)
        self.assertEqual(stats.baseline_created, 1)
        self.assertEqual(stats.suppressed_baseline, 1)
        self.assertEqual(AnimeFranchiseDiscoveredEntry.objects.count(), 1)
        mock_notify.assert_not_called()

    def test_dry_run_counts_baseline_when_state_exists_without_completed_baseline(self):
        state = AnimeFranchiseDiscoveryState.objects.create(
            user=self.user,
            component_root_mal_id="1",
            first_scanned_at=timezone.now(),
            last_error="previous discovery error",
            last_error_at=timezone.now(),
        )

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.baseline_created, 1)
        self.assertFalse(
            AnimeFranchiseDiscoveredEntry.objects.filter(
                user=self.user,
                component_root_mal_id="1",
            ).exists()
        )
        state.refresh_from_db()
        self.assertIsNone(state.baseline_completed_at)
        self.assertEqual(state.last_error, "previous discovery error")


    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_second_scan_after_empty_baseline_notifies_new_candidate(self, mock_notify):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        self.assertEqual(stats.notifications_queued, 1)
        mock_notify.assert_called_once()

    def test_mixed_case_notifiable_section_key_is_normalized(self):
        stats = self.service([self.candidate(section_key="Specials")]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.visible_candidates, 1)
        self.assertEqual(stats.skipped_not_notifiable_section, 0)

    def test_mixed_case_excluded_section_key_is_normalized(self):
        stats = self.service(
            [self.candidate(section_key="RELATED_SERIES")]
        ).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.visible_candidates, 0)
        self.assertEqual(stats.skipped_not_notifiable_section, 1)

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_imported_and_tracked_candidates_are_suppressed(self, mock_notify):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        item = Item.objects.create(
            media_id="3",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Tracked",
            image="https://example.com/img.jpg",
        )
        Anime.objects.create(user=self.user, item=item, status=Status.PLANNING.value)

        stats = self.service(
            [self.candidate("2"), self.candidate("3")]
        ).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            imported_media_ids={"2"},
        )

        self.assertEqual(stats.suppressed_imported_in_same_run, 1)
        self.assertEqual(stats.suppressed_already_tracked, 1)
        self.assertEqual(
            AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2").notification_suppressed_reason,
            "imported_in_same_run",
        )
        self.assertEqual(
            AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="3").notification_suppressed_reason,
            "already_tracked",
        )
        mock_notify.assert_not_called()

    def test_fingerprint_ignores_related_series_and_excluded_formats(self):
        candidates = [
            self.candidate("2"),
            self.candidate("3", section_key="related_series"),
            self.candidate("4", anime_media_type="CM"),
        ]
        stats = self.service(candidates).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        state = AnimeFranchiseDiscoveryState.objects.get(user=self.user)
        expected = AnimeFranchiseDiscoveryService.build_fingerprint(
            [self.candidate("2")]
        )
        self.assertEqual(state.last_fingerprint, expected)
        self.assertEqual(stats.skipped_not_notifiable_section, 1)
        self.assertEqual(stats.skipped_excluded_format, 1)

    def test_dry_run_does_not_persist(self):
        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.baseline_created, 1)
        self.assertFalse(AnimeFranchiseDiscoveryState.objects.exists())
        self.assertFalse(AnimeFranchiseDiscoveredEntry.objects.exists())


class FakeUiPipeline:
    def __init__(self, payload):
        self.payload = payload

    def run(self, snapshot):
        return self.payload


class AnimeFranchiseDiscoveryProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="projection-service-user"
        )
        self.snapshot = SimpleNamespace()

    def service(self, candidates):
        return AnimeFranchiseDiscoveryService(projection=FakeProjection(candidates))

    def candidate(self, media_id="2", section_key="specials", anime_media_type="ova"):
        return FranchiseDiscoveryCandidate(
            media_id=media_id,
            title=f"Anime {media_id}",
            section_key=section_key,
            section_label="Specials",
            relation_type="side_story",
            source_media_id="1",
            anime_media_type=anime_media_type,
            root_title="Root",
        )

    def payload(self, *, series_entries=None, sections=None):
        return SimpleNamespace(
            display_title="Root",
            series={"entries": series_entries or []},
            sections=sections or [],
        )

    def entry(self, media_id="2", title="Anime 2", anime_media_type="ova"):
        return {
            "media_id": media_id,
            "title": title,
            "anime_media_type": anime_media_type,
            "relation_type": "spin_off",
            "relation_source_media_id": "1",
        }

    def test_notifiable_section_wins_over_related_series(self):
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    sections=[
                        {
                            "key": "related_series",
                            "title": "Related Series",
                            "entries": [self.entry()],
                        },
                        {
                            "key": "spin_offs",
                            "title": "Spin-Offs",
                            "entries": [self.entry()],
                        },
                    ]
                )
            )
        )

        candidates = projection.project(SimpleNamespace())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].section_key, "spin_offs")

    def test_series_line_wins_over_secondary_section(self):
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    series_entries=[self.entry()],
                    sections=[
                        {
                            "key": "spin_offs",
                            "title": "Spin-Offs",
                            "entries": [self.entry()],
                        }
                    ],
                )
            )
        )

        candidates = projection.project(SimpleNamespace())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].section_key, "series_line")

    def test_main_story_extras_continuity_key_is_notifiable(self):
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    sections=[
                        {
                            "key": "continuity_extras",
                            "title": "Main Story Extras",
                            "entries": [self.entry()],
                        }
                    ]
                )
            )
        )
        service = AnimeFranchiseDiscoveryService(projection=projection)

        stats = service.process_snapshot(
            user=self.user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.visible_candidates, 1)
        self.assertEqual(stats.skipped_not_notifiable_section, 0)


    def test_valid_format_wins_over_higher_priority_excluded_format(self):
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    series_entries=[self.entry(anime_media_type="cm")],
                    sections=[
                        {
                            "key": "spin_offs",
                            "title": "Spin-Offs",
                            "entries": [self.entry(anime_media_type="ova")],
                        }
                    ],
                )
            )
        )

        candidates = projection.project(SimpleNamespace())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].section_key, "spin_offs")
        self.assertEqual(candidates[0].anime_media_type, "ova")

    def test_series_line_tv_wins_over_secondary_valid_format(self):
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    series_entries=[self.entry(anime_media_type="tv")],
                    sections=[
                        {
                            "key": "spin_offs",
                            "title": "Spin-Offs",
                            "entries": [self.entry(anime_media_type="ova")],
                        }
                    ],
                )
            )
        )

        candidates = projection.project(SimpleNamespace())

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].section_key, "series_line")

    def test_invalid_media_ids_are_counted_individually(self):
        user = get_user_model().objects.create_user(username="invalid-media-bulk-user")
        candidates = [self._candidate_with_blank_media_id() for _ in range(3)]
        service = AnimeFranchiseDiscoveryService(projection=FakeProjection(candidates))

        stats = service.process_snapshot(
            user=user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
        )

        self.assertEqual(stats.skipped_invalid_media_id, 3)
        self.assertFalse(AnimeFranchiseDiscoveredEntry.objects.exists())

    def test_related_series_only_is_skipped_as_not_notifiable(self):
        user = get_user_model().objects.create_user(username="projection-user")
        projection = AnimeFranchiseDiscoveryProjection(
            ui_pipeline=FakeUiPipeline(
                self.payload(
                    sections=[
                        {
                            "key": "related_series",
                            "title": "Related Series",
                            "entries": [self.entry()],
                        }
                    ]
                )
            )
        )
        service = AnimeFranchiseDiscoveryService(projection=projection)

        stats = service.process_snapshot(
            user=user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
        )

        self.assertEqual(stats.skipped_not_notifiable_section, 1)
        self.assertFalse(AnimeFranchiseDiscoveredEntry.objects.exists())

    def test_invalid_media_id_is_skipped(self):
        user = get_user_model().objects.create_user(username="invalid-media-user")
        service = AnimeFranchiseDiscoveryService(
            projection=FakeProjection([self._candidate_with_blank_media_id()])
        )

        stats = service.process_snapshot(
            user=user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
        )

        self.assertEqual(stats.skipped_invalid_media_id, 1)
        self.assertFalse(AnimeFranchiseDiscoveredEntry.objects.exists())

    def _candidate_with_blank_media_id(self):
        return FranchiseDiscoveryCandidate(
            media_id="",
            title="Missing ID",
            section_key="specials",
            anime_media_type="ova",
        )

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_existing_baseline_reason_is_not_erased_or_renotified(self, mock_notify):
        self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        self.assertEqual(discovery.notification_suppressed_reason, "baseline")
        self.assertEqual(stats.notifications_queued, 0)
        mock_notify.assert_not_called()

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_notifications_disabled_is_temporary_and_requeues_after_reactivation(
        self, mock_notify
    ):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        disabled_stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        self.assertIsNone(discovery.notification_queued_at)
        self.assertIsNone(discovery.notified_at)
        self.assertEqual(discovery.notification_suppressed_reason, "")
        self.assertEqual(disabled_stats.suppressed_notifications_disabled, 1)
        self.assertEqual(disabled_stats.notifications_queued, 0)

        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()
        mock_notify.assert_not_called()

        enabled_stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(enabled_stats.notifications_queued, 1)
        self.assertIsNotNone(discovery.notification_queued_at)
        self.assertEqual(discovery.notification_suppressed_reason, "")
        self.assertIsNone(discovery.notified_at)
        mock_notify.assert_called_once_with(self.user.id, discovery.id)


    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_notifications_disabled_reactivation_window_expires(self, mock_notify):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        expired_first_seen_at = (
            timezone.now()
            - DISCOVERY_NOTIFICATION_REACTIVATION_WINDOW
            - timezone.timedelta(days=1)
        )
        AnimeFranchiseDiscoveredEntry.objects.filter(id=discovery.id).update(
            first_seen_at=expired_first_seen_at
        )
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 0)
        self.assertEqual(stats.reactivation_window_expired, 1)
        self.assertEqual(stats.notifications_suppressed, 0)
        self.assertEqual(discovery.notification_suppressed_reason, "")
        self.assertIsNone(discovery.notified_at)
        self.assertIsNone(discovery.notification_queued_at)
        mock_notify.assert_not_called()

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_dry_run_counts_expired_reactivation_window_without_writes(
        self, mock_notify
    ):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        expired_first_seen_at = (
            timezone.now()
            - DISCOVERY_NOTIFICATION_REACTIVATION_WINDOW
            - timezone.timedelta(days=1)
        )
        AnimeFranchiseDiscoveredEntry.objects.filter(id=discovery.id).update(
            first_seen_at=expired_first_seen_at
        )
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()
        discovery.refresh_from_db()
        last_seen_at = discovery.last_seen_at
        notification_queued_at = discovery.notification_queued_at

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 0)
        self.assertEqual(stats.reactivation_window_expired, 1)
        self.assertEqual(stats.notifications_suppressed, 0)
        self.assertEqual(discovery.notification_suppressed_reason, "")
        self.assertIsNone(discovery.notified_at)
        self.assertEqual(discovery.notification_queued_at, notification_queued_at)
        self.assertEqual(discovery.last_seen_at, last_seen_at)
        mock_notify.assert_not_called()

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_legacy_notifications_disabled_reason_is_cleared_when_reactivated(
        self, mock_notify
    ):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_suppressed_reason="notifications_disabled",
        )
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()

        stats = self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 1)
        self.assertEqual(discovery.notification_suppressed_reason, "")
        mock_notify.assert_called_once_with(self.user.id, discovery.id)

    def test_notified_discovery_is_not_later_marked_already_tracked(self):
        self.service([]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notified_at="2026-01-01T00:00:00Z",
        )
        item = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Tracked",
            image="https://example.com/img.jpg",
        )
        Anime.objects.create(user=self.user, item=item, status=Status.PLANNING.value)

        self.service([self.candidate()]).process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(discovery.notification_suppressed_reason, "")


class AnimeFranchiseDiscoveryLockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="lock-user")

    @patch("app.services.anime_franchise_discovery.cache")
    def test_process_snapshot_skips_when_user_root_lock_exists(self, mock_cache):
        mock_cache.add.return_value = False
        service = AnimeFranchiseDiscoveryService(
            projection=FakeProjection(
                [
                    FranchiseDiscoveryCandidate(
                        media_id="2",
                        title="Anime 2",
                        section_key="specials",
                        anime_media_type="ova",
                    )
                ]
            )
        )

        stats = service.process_snapshot(
            user=self.user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
        )

        self.assertEqual(stats.discovery_lock_skipped, 1)
        self.assertEqual(stats.visible_candidates, 0)
        self.assertFalse(AnimeFranchiseDiscoveryState.objects.exists())
        mock_cache.delete.assert_not_called()

    @patch("app.services.anime_franchise_discovery.cache")
    def test_dry_run_bypasses_user_root_lock(self, mock_cache):
        mock_cache.add.return_value = False
        service = AnimeFranchiseDiscoveryService(
            projection=FakeProjection(
                [
                    FranchiseDiscoveryCandidate(
                        media_id="2",
                        title="Anime 2",
                        section_key="specials",
                        anime_media_type="ova",
                    )
                ]
            )
        )

        stats = service.process_snapshot(
            user=self.user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.discovery_lock_skipped, 0)
        self.assertEqual(stats.visible_candidates, 1)
        self.assertFalse(AnimeFranchiseDiscoveryState.objects.exists())
        self.assertFalse(AnimeFranchiseDiscoveredEntry.objects.exists())
        mock_cache.add.assert_not_called()
        mock_cache.delete.assert_not_called()

    @patch("app.services.anime_franchise_discovery.cache")
    def test_process_snapshot_releases_user_root_lock_after_exception(self, mock_cache):
        mock_cache.add.return_value = True

        class RaisingProjection:
            def project(self, snapshot):
                msg = "projection failed"
                raise RuntimeError(msg)

        service = AnimeFranchiseDiscoveryService(projection=RaisingProjection())

        with self.assertRaises(RuntimeError):
            service.process_snapshot(
                user=self.user,
                snapshot=SimpleNamespace(),
                component_root_mal_id="1",
            )

        mock_cache.delete.assert_called_once_with(
            f"anime-franchise-discovery:{self.user.id}:1"
        )


class AnimeTrackingHelperTests(TestCase):
    def test_bulk_mal_anime_tracked_ids_returns_tracked_subset(self):
        user = get_user_model().objects.create_user(username="bulk-tracking-user")
        for media_id in ["1", "2"]:
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=f"Tracked {media_id}",
                image="https://example.com/img.jpg",
            )
            Anime.objects.create(user=user, item=item, status=Status.PLANNING.value)

        tracked_ids = bulk_mal_anime_tracked_ids(
            user_id=user.id,
            media_ids=["1", "2", "3"],
        )

        self.assertEqual(tracked_ids, {"1", "2"})

    @patch("app.services.anime_franchise_discovery.bulk_mal_anime_tracked_ids")
    def test_discovery_service_uses_bulk_tracking_helper(self, mock_bulk):
        user = get_user_model().objects.create_user(username="bulk-service-user")
        mock_bulk.return_value = set()
        service = AnimeFranchiseDiscoveryService(
            projection=FakeProjection(
                [
                    FranchiseDiscoveryCandidate(
                        media_id="1",
                        title="Anime 1",
                        section_key="specials",
                        anime_media_type="ova",
                    ),
                    FranchiseDiscoveryCandidate(
                        media_id="2",
                        title="Anime 2",
                        section_key="specials",
                        anime_media_type="ova",
                    ),
                ]
            )
        )

        service.process_snapshot(
            user=user,
            snapshot=SimpleNamespace(),
            component_root_mal_id="1",
            dry_run=True,
        )

        mock_bulk.assert_called_once_with(user_id=user.id, media_ids=["1", "2"])


class AnimeFranchiseDiscoveryRetryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="retry-user")
        self.user.franchise_discovery_notifications_enabled = True
        self.user.notification_urls = "https://example.com/notify"
        self.user.save()
        self.snapshot = SimpleNamespace()
        self.candidate = FranchiseDiscoveryCandidate(
            media_id="2",
            title="Anime 2",
            section_key="specials",
            section_label="Specials",
            anime_media_type="ova",
            root_title="Root",
        )
        self.service = AnimeFranchiseDiscoveryService(
            projection=FakeProjection([self.candidate])
        )
        AnimeFranchiseDiscoveryState.objects.create(
            user=self.user,
            component_root_mal_id="1",
            baseline_completed_at=timezone.now(),
        )

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_existing_unnotified_discovery_requeues_after_cooldown(self, mock_notify):
        self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )
        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        old_queued_at = (
            timezone.now()
            - DISCOVERY_NOTIFICATION_RETRY_AFTER
            - timezone.timedelta(minutes=1)
        )
        AnimeFranchiseDiscoveredEntry.objects.filter(id=discovery.id).update(
            notification_queued_at=old_queued_at,
            notified_at=None,
            notification_suppressed_reason="",
        )
        mock_notify.reset_mock()

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 1)
        self.assertGreater(discovery.notification_queued_at, old_queued_at)
        mock_notify.assert_called_once_with(self.user.id, discovery.id)

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_recently_queued_discovery_does_not_requeue_immediately(self, mock_notify):
        discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_queued_at=timezone.now(),
        )

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 0)
        mock_notify.assert_not_called()

    @patch("app.services.anime_franchise_discovery.notify_franchise_discovery_after_commit")
    def test_force_baseline_suppression_suppresses_existing_baseline_root(
        self, mock_notify
    ):
        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            force_baseline_suppression=True,
        )

        discovery = AnimeFranchiseDiscoveredEntry.objects.get(discovered_media_id="2")
        self.assertEqual(stats.suppressed_baseline, 1)
        self.assertEqual(discovery.notification_suppressed_reason, "baseline")
        mock_notify.assert_not_called()

    def test_dry_run_counts_existing_retry_after_cooldown(self):
        discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_queued_at=(
                timezone.now()
                - DISCOVERY_NOTIFICATION_RETRY_AFTER
                - timezone.timedelta(minutes=1)
            ),
        )

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        discovery.refresh_from_db()
        self.assertEqual(stats.notifications_queued, 1)
        self.assertIsNone(discovery.notified_at)

    def test_dry_run_does_not_count_recent_retry(self):
        AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_queued_at=timezone.now(),
        )

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.notifications_queued, 0)

    def test_dry_run_does_not_count_notified_retry(self):
        AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notified_at=timezone.now(),
            notification_queued_at=(
                timezone.now()
                - DISCOVERY_NOTIFICATION_RETRY_AFTER
                - timezone.timedelta(minutes=1)
            ),
        )

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.notifications_queued, 0)

    def test_dry_run_does_not_count_historically_suppressed_retry(self):
        AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_suppressed_reason="baseline",
            notification_queued_at=(
                timezone.now()
                - DISCOVERY_NOTIFICATION_RETRY_AFTER
                - timezone.timedelta(minutes=1)
            ),
        )

        stats = self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
            dry_run=True,
        )

        self.assertEqual(stats.notifications_queued, 0)

    def test_existing_discovery_updates_last_seen_at(self):
        discovery = AnimeFranchiseDiscoveredEntry.objects.create(
            user=self.user,
            component_root_mal_id="1",
            discovered_media_id="2",
            title="Anime 2",
            section_key="specials",
            notification_suppressed_reason="baseline",
        )
        old_seen_at = timezone.now() - timezone.timedelta(days=7)
        AnimeFranchiseDiscoveredEntry.objects.filter(id=discovery.id).update(
            last_seen_at=old_seen_at
        )

        self.service.process_snapshot(
            user=self.user,
            snapshot=self.snapshot,
            component_root_mal_id="1",
        )

        discovery.refresh_from_db()
        self.assertGreater(discovery.last_seen_at, old_seen_at)
