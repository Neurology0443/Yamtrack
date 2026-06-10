# ruff: noqa: D101,D102
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app.services import anime_franchise_cache


@override_settings(
    ANIME_FRANCHISE_CACHE_TTL_DAYS=365,
    ANIME_FRANCHISE_CACHE_FRESH_DAYS=30,
    ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS=24,
    ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS=12,
    ANIME_FRANCHISE_QUEUE_LOCK_MINUTES=30,
    ANIME_FRANCHISE_TASK_LOCK_MINUTES=60,
    ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION=1,
)
class AnimeFranchiseCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.entry = {
            "media_id": "100",
            "source": "mal",
            "media_type": "anime",
            "title": "Root",
        }
        self.payload = {
            "schema_version": 1,
            "root_media_id": "100",
            "display_title": "Root",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [dict(self.entry)],
            },
            "sections": [
                {
                    "key": "movies",
                    "title": "Movies",
                    "entries": [dict(self.entry, media_id="101", title="Movie")],
                    "visible_in_ui": True,
                    "hidden_if_empty": True,
                },
            ],
            "truncated": False,
            "node_count": 2,
        }

    def test_save_and_load_payload_updates_access_metadata(self):
        anime_franchise_cache.save_payload("100", self.payload, node_count=1)

        payload, meta = anime_franchise_cache.load_payload("100")

        self.assertEqual(payload["root_media_id"], "100")
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(meta["node_count"], 1)
        self.assertTrue(meta["last_accessed_at"])

    def test_incompatible_schema_is_ignored_but_meta_is_returned(self):
        bad_payload = {**self.payload, "schema_version": 999}
        cache.set(anime_franchise_cache.get_payload_key("100"), bad_payload)

        payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNone(payload)
        self.assertEqual(meta["schema_version"], 1)

    def test_stale_payload_is_displayable_but_schedulable(self):
        stale_time = timezone.now() - timedelta(days=31)
        anime_franchise_cache.save_payload("100", self.payload, fetched_at=stale_time)
        payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNotNone(payload)
        self.assertFalse(anime_franchise_cache.is_fresh(meta))
        self.assertTrue(
            anime_franchise_cache.can_schedule_build(meta, has_payload=True),
        )


    def test_missing_payload_returns_empty_meta(self):
        payload, meta = anime_franchise_cache.load_payload("404")

        self.assertIsNone(payload)
        self.assertIsNone(meta["fetched_at"])
        self.assertEqual(meta["last_error_message"], "")

    def test_fresh_payload_with_has_payload_blocks_scheduling(self):
        anime_franchise_cache.save_payload("100", self.payload)
        _payload, meta = anime_franchise_cache.load_payload("100")

        self.assertTrue(anime_franchise_cache.is_fresh(meta))
        self.assertFalse(
            anime_franchise_cache.can_schedule_build(meta, has_payload=True),
        )

    def test_recent_attempt_respects_build_cooldown(self):
        meta = anime_franchise_cache.mark_attempt("100")

        self.assertFalse(anime_franchise_cache.can_schedule_build(meta))

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    def test_enqueue_failure_releases_queue_lock(self, mock_delay):
        mock_delay.side_effect = RuntimeError("queue down")

        self.assertFalse(anime_franchise_cache.maybe_schedule_build("100"))
        self.assertIsNone(cache.get(anime_franchise_cache.get_queue_lock_key("100")))

    def test_mark_error_preserves_existing_payload_metadata(self):
        anime_franchise_cache.save_payload("100", self.payload)
        before_payload, before_meta = anime_franchise_cache.load_payload("100")

        meta = anime_franchise_cache.mark_error("100", "boom")
        after_payload, _after_meta = anime_franchise_cache.load_payload("100")

        self.assertEqual(after_payload, before_payload)
        self.assertEqual(meta["fetched_at"], before_meta["fetched_at"])
        self.assertEqual(meta["last_success_at"], before_meta["last_success_at"])
        self.assertEqual(meta["node_count"], before_meta["node_count"])
        self.assertEqual(meta["truncated"], before_meta["truncated"])
        self.assertEqual(meta["truncation_reason"], before_meta["truncation_reason"])
        self.assertEqual(meta["last_error_message"], "boom")



    def test_normalize_meta_empty_dict_keeps_required_defaults(self):
        meta = anime_franchise_cache.normalize_meta({})

        self.assertEqual(
            meta["schema_version"],
            1,
        )
        self.assertTrue(meta["last_accessed_at"])
        self.assertEqual(meta["last_error_message"], "")
        self.assertEqual(meta["truncation_reason"], "")
        self.assertEqual(meta["node_count"], 0)
        self.assertFalse(meta["truncated"])

    def test_invalid_payload_shapes_are_rejected(self):
        cases = []
        payload = deepcopy(self.payload)
        payload["sections"][0].pop("key")
        cases.append(payload)
        payload = deepcopy(self.payload)
        payload["sections"][0].pop("title")
        cases.append(payload)
        payload = deepcopy(self.payload)
        payload["series"]["entries"] = {}
        cases.append(payload)
        payload = deepcopy(self.payload)
        payload["sections"][0]["entries"] = {}
        cases.append(payload)
        for required_key in ("media_id", "source", "media_type", "title"):
            payload = deepcopy(self.payload)
            payload["series"]["entries"][0].pop(required_key)
            cases.append(payload)

        for payload in cases:
            with self.subTest(payload=payload):
                self.assertFalse(anime_franchise_cache.is_valid_payload(payload))
                with self.assertRaises(ValueError):
                    anime_franchise_cache.save_payload("bad", payload)

    def test_save_payload_rejects_non_json_safe_payload(self):
        payload = deepcopy(self.payload)
        payload["series"]["entries"].append(
            {
                "media_id": "102",
                "source": "mal",
                "media_type": "anime",
                "title": "Bad",
                "bad": object(),
            }
        )

        with self.assertRaises(ValueError):
            anime_franchise_cache.save_payload("100", payload)
        self.assertIsNone(cache.get(anime_franchise_cache.get_payload_key("100")))

    def test_save_payload_rejects_user_specific_keys(self):
        for forbidden_key in ("media", "item", "progress", "status", "user_id", "html"):
            payload = deepcopy(self.payload)
            payload["series"]["entries"][0][forbidden_key] = "bad"

            with self.subTest(forbidden_key=forbidden_key):
                with self.assertRaises(ValueError):
                    anime_franchise_cache.save_payload("100", payload)
                self.assertIsNone(cache.get(anime_franchise_cache.get_payload_key("100")))

    def test_invalid_payload_load_returns_none_and_normalized_meta(self):
        cache.set(
            anime_franchise_cache.get_payload_key("100"),
            {"schema_version": 1, "root_media_id": "100"},
        )

        payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNone(payload)
        self.assertEqual(meta["schema_version"], 1)
        self.assertTrue(meta["last_accessed_at"])



    def test_normalize_meta_with_invalid_node_count_falls_back_to_zero(self):
        meta = anime_franchise_cache.normalize_meta({"node_count": "abc"})

        self.assertEqual(meta["node_count"], 0)
        self.assertEqual(meta["schema_version"], 1)
        self.assertTrue(meta["last_accessed_at"])

    def test_load_payload_with_corrupt_meta_node_count_does_not_crash(self):
        anime_franchise_cache.save_payload("100", self.payload)
        meta = anime_franchise_cache.normalize_meta(
            cache.get(anime_franchise_cache.get_meta_key("100")),
        )
        meta["node_count"] = "abc"
        cache.set(anime_franchise_cache.get_meta_key("100"), meta)

        payload, loaded_meta = anime_franchise_cache.load_payload("100")

        self.assertIsNotNone(payload)
        self.assertEqual(loaded_meta["node_count"], 0)

    def test_load_payload_rejects_cached_payload_with_user_specific_keys(self):
        payload = deepcopy(self.payload)
        payload["series"]["entries"][0]["progress"] = 4
        cache.set(anime_franchise_cache.get_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        loaded_payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNone(loaded_payload)
        self.assertEqual(meta["schema_version"], 1)

    def test_load_payload_rejects_cached_section_payload_with_user_specific_keys(self):
        payload = deepcopy(self.payload)
        payload["sections"][0]["entries"][0]["media"] = {"id": 1}
        cache.set(anime_franchise_cache.get_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        loaded_payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNone(loaded_payload)
        self.assertEqual(meta["schema_version"], 1)

    def test_load_payload_rejects_cached_non_json_safe_payload(self):
        payload = deepcopy(self.payload)
        payload["series"]["entries"][0]["bad"] = object()
        cache.set(anime_franchise_cache.get_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        loaded_payload, meta = anime_franchise_cache.load_payload("100")

        self.assertIsNone(loaded_payload)
        self.assertEqual(meta["schema_version"], 1)

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    def test_queue_lock_prevents_duplicate_scheduling(self, mock_delay):
        self.assertTrue(anime_franchise_cache.maybe_schedule_build("100"))
        self.assertFalse(anime_franchise_cache.maybe_schedule_build("100"))

        mock_delay.assert_called_once_with("100")

    def test_recent_error_respects_retry_cooldown(self):
        meta = anime_franchise_cache.mark_error("100", "boom")

        self.assertFalse(anime_franchise_cache.can_schedule_build(meta))
