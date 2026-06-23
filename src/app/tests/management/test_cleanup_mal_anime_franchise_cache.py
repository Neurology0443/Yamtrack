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

    @patch("app.services.anime_franchise_cache.maybe_schedule_build")
    def test_schedule_rebuild_uses_scheduler(self, mock_schedule):
        mock_schedule.return_value = True
        cache.set(anime_franchise_cache.get_global_payload_key("100"), {"legacy": True})

        output = self._run("--media-id", "100", "--apply", "--schedule-rebuild")

        mock_schedule.assert_called_once_with(
            "100", payload_meta=None, has_payload=False
        )
        self.assertIn("scheduled_rebuilds: 1", output)
