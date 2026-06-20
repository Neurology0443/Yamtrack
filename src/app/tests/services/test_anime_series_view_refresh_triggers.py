# ruff: noqa: D101, D102

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app.models import Anime, AnimeImportScanState, Item, MediaTypes, Sources, Status
from app.services.anime_series_view_refresh_queue import refresh_queue_lock_key
from app.services.anime_series_view_refresh_triggers import (
    AnimeSeriesViewRefreshTriggerService,
)


class AnimeSeriesViewRefreshTriggerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="triggers")

    @patch("app.tasks.refresh_anime_series_view_projection.delay")
    def test_manual_add_enqueues_after_commit(self, delay):
        service = AnimeSeriesViewRefreshTriggerService()

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            service.schedule_manual_add(
                user=self.user,
                media_id="502",
            )

        delay.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        delay.assert_called_once_with(self.user.id, ["502"])

    @patch("app.tasks.refresh_anime_series_view_projection.delay")
    def test_import_batch_normalizes_seed_and_root_in_one_on_commit(self, delay):
        service = AnimeSeriesViewRefreshTriggerService()

        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_import_batch(
                user=self.user,
                seed_media_id="10",
                component_root_media_id="1",
            )

        delay.assert_called_once_with(
            self.user.id,
            ["1", "10"],
        )

    @patch("app.tasks.refresh_anime_series_view_projection.delay")
    def test_queue_lock_prevents_identical_double_enqueue(self, delay):
        service = AnimeSeriesViewRefreshTriggerService()

        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_manual_add(user=self.user, media_id="502")
            service.schedule_manual_add(user=self.user, media_id="502")

        delay.assert_called_once_with(self.user.id, ["502"])

    @patch("app.tasks.refresh_anime_series_view_projection.delay")
    def test_queue_lock_is_deleted_when_enqueue_fails(self, delay):
        delay.side_effect = RuntimeError("boom")
        service = AnimeSeriesViewRefreshTriggerService()
        lock_key = refresh_queue_lock_key(self.user.id, ["502"])

        with (
            self.assertLogs(
                "app.services.anime_series_view_refresh_triggers",
                level="ERROR",
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            service.schedule_manual_add(user=self.user, media_id="502")

        self.assertIsNone(cache.get(lock_key))

    @patch("app.tasks.refresh_anime_series_view_projection.delay")
    def test_delete_and_import_use_the_same_async_enqueue_path(self, delay):
        service = AnimeSeriesViewRefreshTriggerService()

        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_delete(user=self.user, media_id="20")
            service.schedule_import_batch(
                user=self.user,
                seed_media_id="30",
                component_root_media_id="10",
            )

        self.assertEqual(
            delay.call_args_list,
            [
                ((self.user.id, ["20"]), {}),
                ((self.user.id, ["10", "30"]), {}),
            ],
        )

    @patch(
        "app.signals.AnimeSeriesViewRefreshTriggerService.schedule_import_batch"
    )
    def test_multi_entry_import_skips_partial_refreshes_and_triggers_once_on_success(
        self,
        schedule_import_batch,
    ):
        for media_id in ("20", "21", "22"):
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=f"Imported {media_id}",
                image="https://example.com/image.jpg",
            )
            anime = Anime(
                user=self.user,
                item=item,
                status=Status.PLANNING.value,
            )
            anime._skip_hot_priority = True
            anime.save()

        now = timezone.now()
        AnimeImportScanState.objects.create(
            user=self.user,
            seed_mal_id="20",
            profile_key="satellites",
            next_scan_at=now,
            last_success_at=now,
            component_root_mal_id="10",
        )

        schedule_import_batch.assert_called_once()
        self.assertEqual(
            schedule_import_batch.call_args.kwargs["seed_media_id"],
            "20",
        )
