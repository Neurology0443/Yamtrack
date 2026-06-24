# ruff: noqa: D101,D102
from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from app.services import anime_franchise_cache


@override_settings(
    ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION=1,
    ANIME_FRANCHISE_CACHE_TTL_DAYS=365,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "cleanup-mal-anime-franchise-cache-tests",
        }
    },
)
class CleanupMalAnimeFranchiseCacheCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            "schema_version": 1,
            "root_media_id": "100",
            "canonical_root_media_id": "100",
            "display_title": "Root",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "100",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Root",
                    }
                ],
            },
            "sections": [],
            "payload_role": anime_franchise_cache.PAYLOAD_ROLE_GLOBAL,
            "payload_kind": anime_franchise_cache.PAYLOAD_KIND_CANONICAL_FRANCHISE,
            "build_seed_media_id": "100",
        }

    def _run(self, *args):
        out = StringIO()
        call_command("cleanup_mal_anime_franchise_cache", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_does_not_delete_legacy_global(self):
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})

        output = self._run("--media-id", "100", "--verbose")

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )
        self.assertIn("dry_run: True", output)
        self.assertIn("legacy_global_deleted: 1", output)

    def test_apply_deletes_legacy_global_without_payload_role(self):
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})
        cache.set(
            anime_franchise_cache.get_global_meta_key("100"), {"schema_version": 1}
        )

        self._run("--media-id", "100", "--apply")

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_global_meta_key("100")))

    def test_apply_deletes_invalid_global_payload(self):
        invalid = deepcopy(self.payload)
        invalid["payload_role"] = anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED
        cache.set(anime_franchise_cache.get_global_payload_key("100"), invalid)

        output = self._run("--media-id", "100", "--apply")

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )
        self.assertIn("invalid_global_deleted: 1", output)

    def test_apply_preserves_valid_global_payload(self):
        anime_franchise_cache.save_global_payload("100", self.payload)

        output = self._run("--media-id", "100", "--apply")

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )
        self.assertIn("global_valid: 1", output)

    def test_apply_preserves_scoped_and_alias(self):
        scoped = deepcopy(self.payload)
        scoped.update(
            {
                "payload_role": anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED,
                "detail_payload_kind": (
                    anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT
                ),
                "rule_key": "non_tv_seed_to_tv_context_v1",
                "build_seed_media_id": "100",
                "global_canonical_root_media_id": "200",
            }
        )
        anime_franchise_cache.save_scoped_payload("100", scoped)
        cache.set(
            anime_franchise_cache.get_alias_key("100"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="200", aliased_media_id="100"
            ),
        )

        self._run("--media-id", "100", "--apply")

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_scoped_payload_key("100"))
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("100")))

    def test_apply_preserves_build_meta(self):
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})
        anime_franchise_cache.update_build_meta("100", {"last_error_message": "boom"})

        self._run("--media-id", "100", "--apply")

        self.assertEqual(
            cache.get(anime_franchise_cache.get_build_meta_key("100"))[
                "last_error_message"
            ],
            "boom",
        )

    @patch("app.services.anime_franchise_cache.maybe_schedule_build")
    def test_media_id_missing_key_does_not_schedule_rebuild(self, mock_schedule):
        output = self._run("--media-id", "404", "--apply", "--schedule-rebuild")

        mock_schedule.assert_not_called()
        self.assertIn("processed_global_keys: 0", output)
        self.assertIn("missing_global_key: 1", output)

    @patch("app.services.anime_franchise_cache.maybe_schedule_build")
    def test_schedule_rebuild_uses_scheduler(self, mock_schedule):
        mock_schedule.return_value = True
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})

        output = self._run("--media-id", "100", "--apply", "--schedule-rebuild")

        mock_schedule.assert_called_once_with(
            "100", payload_meta=None, has_payload=False
        )
        self.assertIn("scheduled_rebuilds: 1", output)

    @patch("app.services.anime_franchise_cache.maybe_schedule_build")
    def test_schedule_rebuild_only_after_actual_delete(self, mock_schedule):
        anime_franchise_cache.save_global_payload("100", self.payload)

        self._run("--media-id", "100", "--apply", "--schedule-rebuild")

        mock_schedule.assert_not_called()

    @patch(
        "app.management.commands.cleanup_mal_anime_franchise_cache.Command._iter_raw_keys"
    )
    def test_scanner_ignores_non_global_keys(self, mock_iter_keys):
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})
        cache.set(
            anime_franchise_cache.get_scoped_payload_key("100"), {"bad": "scoped"}
        )
        cache.set(anime_franchise_cache.get_alias_key("100"), {"bad": "alias"})
        cache.set(anime_franchise_cache.get_build_meta_key("100"), {"bad": "build"})
        cache.set(anime_franchise_cache.get_global_meta_key("100"), {"bad": "meta"})
        cache.set(anime_franchise_cache.get_alias_index_key("100"), ["200"])
        cache.set(anime_franchise_cache.get_queue_lock_key("100"), "1")
        cache.set(anime_franchise_cache.get_task_lock_key("100"), "1")
        mock_iter_keys.return_value = iter(
            [
                anime_franchise_cache.get_scoped_payload_key("100"),
                anime_franchise_cache.get_alias_key("100"),
                anime_franchise_cache.get_build_meta_key("100"),
                anime_franchise_cache.get_global_meta_key("100"),
                anime_franchise_cache.get_alias_index_key("100"),
                anime_franchise_cache.get_queue_lock_key("100"),
                anime_franchise_cache.get_task_lock_key("100"),
                anime_franchise_cache.get_global_payload_key("100"),
            ]
        )

        output = self._run("--apply")

        self.assertIn("legacy_global_deleted: 1", output)
        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_scoped_payload_key("100"))
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("100")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_build_meta_key("100")))

    @patch(
        "app.management.commands.cleanup_mal_anime_franchise_cache.Command._iter_raw_keys"
    )
    def test_ambiguous_prefixed_raw_key_is_skipped_safely(self, mock_iter_keys):
        cache.set(":1:mal_anime_franchise_100", {"legacy": True})
        mock_iter_keys.return_value = iter([":1:mal_anime_franchise_100"])

        output = self._run("--apply", "--verbose")

        self.assertIn("processed_global_keys: 0", output)
        self.assertIsNotNone(cache.get(":1:mal_anime_franchise_100"))
