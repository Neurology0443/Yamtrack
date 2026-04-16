# ruff: noqa: D101,D102,D107
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from app.models import Anime, AnimeImportScanState, Item, MediaTypes, Sources, Status
from app.services.anime_franchise_import import FranchiseImportStats
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode


class ImportAnimeFranchiseCommandTests(TestCase):
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

        self.user = get_user_model().objects.create_user(username="importer", password="pwd")

    @patch("app.management.commands.import_anime_franchise.AnimeFranchiseImportService.run")
    def test_dry_run_writes_nothing(self, mock_run):
        mock_run.return_value = FranchiseImportStats(scanned=1, planned_creations=1)
        call_command("import_anime_franchise", "--profile", "continuity", "--dry-run")
        self.assertFalse(Item.objects.exists())
        self.assertFalse(Anime.objects.exists())
        self.assertFalse(AnimeImportScanState.objects.exists())

    @patch("app.providers.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.AnimeFranchiseSnapshotService.build")
    def test_real_dry_run_writes_no_entries_and_no_scan_state(
        self,
        mock_build,
        mock_anime_minimal,
    ):
        seed_item = Item.objects.create(
            media_id="100",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Seed",
            image="https://example.com/100.jpg",
        )
        anime = Anime(
            user=self.user,
            item=seed_item,
            status=Status.IN_PROGRESS.value,
        )
        anime._skip_hot_priority = True
        anime.save()
        node = AnimeNode("100", "Seed", "mal", "tv", "img", None, [])
        mock_build.return_value = AnimeFranchiseSnapshot(
            root_node=node,
            nodes_by_media_id={"100": node},
            all_normalized_relations=[],
            continuity_component=[node],
            series_line=[node],
            direct_anchors=[node],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="100",
        )
        mock_anime_minimal.return_value = {
            "media_id": "100",
            "title": "Seed",
            "image": "https://example.com/100.jpg",
            "source": "mal",
            "media_type": "anime",
            "details": {"raw_media_type": "tv", "start_date": None},
        }

        call_command(
            "import_anime_franchise",
            "--profile",
            "continuity",
            "--user-id",
            str(self.user.id),
            "--dry-run",
        )

        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)
        self.assertEqual(AnimeImportScanState.objects.count(), 0)

    def test_limit_must_be_positive(self):
        with self.assertRaisesMessage(
            CommandError,
            "--limit must be greater than or equal to 1.",
        ):
            call_command(
                "import_anime_franchise",
                "--profile",
                "continuity",
                "--limit",
                "0",
            )

    @patch("app.management.commands.import_anime_franchise.AnimeFranchiseImportService.run")
    def test_refresh_cache_flag_wires_to_service(self, mock_run):
        mock_run.return_value = FranchiseImportStats()
        call_command(
            "import_anime_franchise",
            "--profile",
            "continuity",
            "--refresh-cache",
        )
        self.assertTrue(mock_run.call_args.kwargs["refresh_cache"])

    @patch("app.providers.mal.anime_minimal")
    @patch("app.services.anime_franchise_import.AnimeFranchiseSnapshotService.build")
    def test_live_run_is_idempotent(self, mock_build, mock_anime_minimal):
        seed_item = Item.objects.create(
            media_id="100",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Seed",
            image="https://example.com/100.jpg",
        )
        Anime.objects.create(user=self.user, item=seed_item, status=Status.IN_PROGRESS.value)

        node = AnimeNode("100", "Seed", "mal", "tv", "img", None, [])
        mock_build.return_value = AnimeFranchiseSnapshot(
            root_node=node,
            nodes_by_media_id={"100": node, "101": AnimeNode("101", "S2", "mal", "tv", "img2", None, [])},
            all_normalized_relations=[],
            continuity_component=[node, AnimeNode("101", "S2", "mal", "tv", "img2", None, [])],
            series_line=[node],
            direct_anchors=[node],
            direct_candidates=[],
            has_series_line=True,
            fallback_anchor_media_id="100",
        )
        mock_anime_minimal.return_value = {
            "media_id": "101",
            "title": "S2",
            "image": "https://example.com/101.jpg",
            "source": "mal",
            "media_type": "anime",
            "details": {"raw_media_type": "tv", "start_date": None},
        }

        call_command(
            "import_anime_franchise",
            "--profile",
            "continuity",
            "--user-id",
            str(self.user.id),
            "--refresh-cache",
        )
        call_command("import_anime_franchise", "--profile", "continuity", "--user-id", str(self.user.id), "--full-rescan")

        created = Anime.objects.filter(user=self.user, item__media_id="101").count()
        self.assertEqual(created, 1)
        self.assertEqual(
            mock_anime_minimal.call_args_list[0].kwargs["refresh_cache"],
            True,
        )
        self.assertEqual(
            mock_build.call_args_list[0].kwargs["refresh_cache"],
            True,
        )
