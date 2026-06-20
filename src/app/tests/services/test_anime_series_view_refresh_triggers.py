# ruff: noqa: D101, D102

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Anime, AnimeImportScanState, Item, MediaTypes, Sources, Status
from app.services.anime_series_view_refresh_triggers import (
    AnimeSeriesViewRefreshTriggerService,
)


class AnimeSeriesViewRefreshTriggerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="triggers")

    @patch(
        "app.services.anime_series_view_refresh_triggers."
        "refresh_anime_series_view_best_effort"
    )
    def test_import_batch_aggregates_seed_and_root_in_one_on_commit(self, refresh):
        service = AnimeSeriesViewRefreshTriggerService()

        with self.captureOnCommitCallbacks(execute=True):
            service.schedule_import_batch(
                user=self.user,
                seed_media_id="10",
                component_root_media_id="1",
            )

        refresh.assert_called_once_with(
            user=self.user,
            media_ids=frozenset({"1", "10"}),
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
