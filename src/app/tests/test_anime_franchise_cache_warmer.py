# ruff: noqa: D101,D102
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.services import anime_franchise_cache
from app.services.anime_franchise_cache_warmer import (
    MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
    schedule_mal_anime_franchise_cache_warm,
)


class AnimeFranchiseCacheWarmerTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("app.services.anime_franchise_cache_warmer.transaction.on_commit")
    @patch("app.services.anime_franchise_cache_warmer.current_app.send_task")
    def test_uses_task_name_and_converts_id_to_string(
        self, mock_send_task, mock_on_commit
    ):
        mock_on_commit.side_effect = lambda callback: callback()

        scheduled = schedule_mal_anime_franchise_cache_warm(123)

        self.assertTrue(scheduled)
        mock_on_commit.assert_called_once()
        mock_send_task.assert_called_once_with(
            MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
            args=["123"],
        )

    @patch("app.services.anime_franchise_cache_warmer.transaction.on_commit")
    @patch("app.services.anime_franchise_cache_warmer.current_app.send_task")
    def test_uses_existing_queue_lock(self, mock_send_task, mock_on_commit):
        mock_on_commit.side_effect = lambda callback: callback()

        scheduled = schedule_mal_anime_franchise_cache_warm("123")

        self.assertTrue(scheduled)
        self.assertEqual(
            cache.get(anime_franchise_cache.get_queue_lock_key("123")), "1"
        )

        scheduled = schedule_mal_anime_franchise_cache_warm("123")

        self.assertFalse(scheduled)
        mock_send_task.assert_called_once_with(
            MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
            args=["123"],
        )

    @patch("app.services.anime_franchise_cache_warmer.current_app.send_task")
    def test_existing_queue_lock_does_not_enqueue(self, mock_send_task):
        cache.add(
            anime_franchise_cache.get_queue_lock_key("123"),
            "1",
            timeout=anime_franchise_cache.get_queue_lock_ttl_seconds(),
        )

        with self.captureOnCommitCallbacks(execute=True):
            scheduled = schedule_mal_anime_franchise_cache_warm("123")

        self.assertFalse(scheduled)
        mock_send_task.assert_not_called()

    @patch("app.services.anime_franchise_cache_warmer.current_app.send_task")
    def test_send_task_error_deletes_queue_lock(self, mock_send_task):
        mock_send_task.side_effect = RuntimeError("boom")

        with self.captureOnCommitCallbacks(execute=True):
            scheduled = schedule_mal_anime_franchise_cache_warm("123")

        self.assertFalse(scheduled)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_queue_lock_key("123"))
        )

    def test_module_does_not_import_app_tasks(self):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "services"
            / "anime_franchise_cache_warmer.py"
        )
        source = source_path.read_text()

        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith(("import ", "from "))
        ]

        self.assertNotIn("from app.tasks", import_lines)
        self.assertNotIn("import app.tasks", import_lines)
