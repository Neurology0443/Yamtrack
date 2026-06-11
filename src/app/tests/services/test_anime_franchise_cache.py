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
    ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True,
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


    def _dragon_ball_payload(self):
        return {
            "schema_version": 1,
            "root_media_id": "223",
            "display_title": "Dragon Ball",
            "series": {
                "key": "series_line",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "223",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball",
                    },
                    {
                        "media_id": "813",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball Z",
                    },
                    {
                        "media_id": "269",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Dragon Ball GT",
                    },
                ],
            },
            "sections": [
                {
                    "key": "continuity_extras",
                    "title": "Main Story Extras",
                    "entries": [
                        {
                            "media_id": "225",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball Movie",
                        },
                    ],
                },
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        {
                            "media_id": "999",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball Special",
                        },
                    ],
                },
                {
                    "key": "spin_offs",
                    "title": "Spin Offs",
                    "entries": [
                        {
                            "media_id": "998",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball Spin Off",
                        },
                    ],
                },
                {
                    "key": "alternatives",
                    "title": "Alternatives",
                    "entries": [
                        {
                            "media_id": "996",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball Alternative",
                        },
                    ],
                },
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "entries": [
                        {
                            "media_id": "997",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Dragon Ball Related",
                        },
                    ],
                },
            ],
        }

    def test_extract_payload_media_ids_from_series_and_sections(self):
        payload = self._dragon_ball_payload()
        payload["series"]["entries"] = payload["series"]["entries"][:2]

        self.assertEqual(
            anime_franchise_cache.extract_payload_media_ids(payload),
            {"223", "813", "225", "999", "998", "997", "996"},
        )

    def test_extract_series_media_ids_only_reads_series_entries(self):
        payload = self._dragon_ball_payload()

        self.assertEqual(
            anime_franchise_cache.extract_series_media_ids(payload),
            {"223", "813", "269"},
        )
        self.assertIn("225", anime_franchise_cache.extract_payload_media_ids(payload))
        self.assertNotIn("225", anime_franchise_cache.extract_series_media_ids(payload))

    def test_extract_aliasable_media_ids_reads_series_and_continuity_extras_only(self):
        payload = self._dragon_ball_payload()

        self.assertEqual(
            anime_franchise_cache.extract_aliasable_media_ids(payload),
            {"223", "813", "269", "225"},
        )
        self.assertIn("999", anime_franchise_cache.extract_payload_media_ids(payload))
        aliasable_ids = anime_franchise_cache.extract_aliasable_media_ids(payload)
        self.assertNotIn("999", aliasable_ids)
        self.assertNotIn("998", aliasable_ids)
        self.assertNotIn("997", aliasable_ids)
        self.assertNotIn("996", aliasable_ids)

    def test_determine_canonical_media_id_from_series_line(self):
        self.assertEqual(
            anime_franchise_cache.determine_canonical_media_id(
                self._dragon_ball_payload(),
                "269",
            ),
            "223",
        )

    def test_prepare_payload_for_aliasing_adds_internal_metadata(self):
        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="269",
                truncated=False,
            )
        )

        self.assertEqual(canonical_id, "223")
        self.assertEqual(prepared["root_media_id"], "223")
        self.assertEqual(prepared["canonical_root_media_id"], "223")
        self.assertIn("269", prepared["aliasable_media_ids"])
        self.assertIn("269", aliasable_ids)
        self.assertIn("225", prepared["covered_media_ids"])
        self.assertIn("225", prepared["aliasable_media_ids"])
        self.assertNotIn("999", prepared["aliasable_media_ids"])
        self.assertNotIn("998", prepared["aliasable_media_ids"])
        self.assertNotIn("997", prepared["aliasable_media_ids"])
        self.assertNotIn("996", prepared["aliasable_media_ids"])
        self.assertEqual(prepared["display_title"], "Dragon Ball")

    def test_prepare_payload_for_aliasing_truncated_keeps_seed_as_canonical(self):
        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="269",
                truncated=True,
                aliases_enabled=True,
            )
        )

        self.assertEqual(canonical_id, "269")
        self.assertEqual(prepared["root_media_id"], "269")
        self.assertEqual(prepared["canonical_root_media_id"], "269")
        self.assertEqual(prepared["aliasable_media_ids"], ["269"])
        self.assertIn("225", prepared["covered_media_ids"])
        self.assertEqual(aliasable_ids, {"269"})

    def test_prepare_payload_for_aliasing_aliases_disabled_keeps_seed_as_canonical(
        self,
    ):
        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="269",
                truncated=False,
                aliases_enabled=False,
            )
        )

        self.assertEqual(canonical_id, "269")
        self.assertEqual(prepared["root_media_id"], "269")
        self.assertEqual(prepared["canonical_root_media_id"], "269")
        self.assertEqual(prepared["aliasable_media_ids"], ["269"])
        self.assertEqual(aliasable_ids, {"269"})

    def test_prepare_payload_for_aliasing_includes_continuity_extra_seed(self):
        payload = self._dragon_ball_payload()

        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="225",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertEqual(canonical_id, "223")
        self.assertIn("225", prepared["covered_media_ids"])
        self.assertIn("225", prepared["aliasable_media_ids"])
        self.assertIn("225", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_uncovered_seed(self):
        payload = self._dragon_ball_payload()

        prepared, _canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="123456",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertNotIn("123456", prepared["covered_media_ids"])
        self.assertNotIn("123456", prepared["aliasable_media_ids"])
        self.assertNotIn("123456", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_covered_special_seed(self):
        payload = self._dragon_ball_payload()

        prepared, _canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="999",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertIn("999", prepared["covered_media_ids"])
        self.assertNotIn("999", prepared["aliasable_media_ids"])
        self.assertNotIn("999", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_covered_spinoff_seed(self):
        payload = self._dragon_ball_payload()

        prepared, _canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="998",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertIn("998", prepared["covered_media_ids"])
        self.assertNotIn("998", prepared["aliasable_media_ids"])
        self.assertNotIn("998", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_covered_alternative_seed(
        self,
    ):
        payload = self._dragon_ball_payload()

        prepared, _canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="996",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertIn("996", prepared["covered_media_ids"])
        self.assertNotIn("996", prepared["aliasable_media_ids"])
        self.assertNotIn("996", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_covered_related_series_seed(
        self,
    ):
        payload = self._dragon_ball_payload()

        prepared, _canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="997",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertIn("997", prepared["covered_media_ids"])
        self.assertNotIn("997", prepared["aliasable_media_ids"])
        self.assertNotIn("997", aliasable_ids)

    def test_replace_aliases_creates_lightweight_records_after_save_payload(self):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223", "813", "269"]
        anime_franchise_cache.save_payload("223", payload)

        count = anime_franchise_cache.replace_aliases("223", payload, truncated=False)

        self.assertEqual(count, 2)
        self.assertEqual(
            cache.get(anime_franchise_cache.get_alias_key("813"))["canonical_media_id"],
            "223",
        )
        self.assertEqual(
            cache.get(anime_franchise_cache.get_alias_key("269"))["canonical_media_id"],
            "223",
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("223")))

    def test_replace_aliases_creates_continuity_extra_aliases_only(self):
        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        anime_franchise_cache.save_payload(canonical_id, prepared)

        count = anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertEqual(count, 3)
        self.assertIn("225", prepared["aliasable_media_ids"])
        self.assertIn("225", aliasable_ids)
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("225")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))

        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("999")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("998")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("997")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("996")))

    def test_replace_aliases_creates_alias_for_continuity_extra_build_seed(self):
        payload = self._dragon_ball_payload()

        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="225",
                truncated=False,
                aliases_enabled=True,
            )
        )
        anime_franchise_cache.save_payload(canonical_id, prepared)
        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        alias = cache.get(anime_franchise_cache.get_alias_key("225"))
        self.assertIsNotNone(alias)
        self.assertEqual(alias["canonical_media_id"], "223")

        lookup = anime_franchise_cache.load_payload_for_media("225")
        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "223")
        self.assertEqual(lookup.payload["root_media_id"], "223")

    def test_replace_aliases_preserves_direct_payload_for_non_aliasable_special_seed(
        self,
    ):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "999"
        direct_payload["display_title"] = "Dragon Ball Special"
        direct_payload["series"]["entries"][0]["media_id"] = "999"
        anime_franchise_cache.save_payload("999", direct_payload)

        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="999",
                truncated=False,
                aliases_enabled=True,
            )
        )
        anime_franchise_cache.save_payload(canonical_id, prepared)
        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("999")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_payload_key("999")))

        lookup = anime_franchise_cache.load_payload_for_media("999")
        self.assertFalse(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "999")
        self.assertEqual(lookup.payload["root_media_id"], "999")

    def test_replace_aliases_deletes_old_direct_payload_for_aliased_id(self):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["display_title"] = "Dragon Ball GT"
        direct_payload["series"]["entries"][0]["media_id"] = "269"
        anime_franchise_cache.save_payload("269", direct_payload)
        payload = self._dragon_ball_payload()
        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        anime_franchise_cache.save_payload(canonical_id, prepared)

        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertIsNone(cache.get(anime_franchise_cache.get_payload_key("269")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_meta_key("269")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_payload_key("223")))

    def test_delete_aliases_for_canonical_preserves_alias_owned_by_other_canonical(
        self,
    ):
        cache.set(
            anime_franchise_cache.get_alias_index_key("111"),
            ["269"],
            timeout=60,
        )
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
            timeout=60,
        )

        anime_franchise_cache.delete_aliases_for_canonical("111")

        alias = cache.get(anime_franchise_cache.get_alias_key("269"))
        self.assertEqual(alias["canonical_media_id"], "223")

    def test_replace_aliases_skips_truncated_payload(self):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223", "269"]
        cache.set(
            anime_franchise_cache.get_alias_index_key("223"),
            ["269"],
            timeout=60,
        )
        cache.set(anime_franchise_cache.get_alias_key("269"), {"bad": "alias"})

        count = anime_franchise_cache.replace_aliases("223", payload, truncated=True)

        self.assertEqual(count, 0)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    def test_load_payload_for_media_prefers_direct_payload_over_alias(self):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["display_title"] = "Dragon Ball GT"
        direct_payload["series"]["entries"][0]["media_id"] = "269"
        anime_franchise_cache.save_payload("269", direct_payload)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertFalse(lookup.alias_hit)
        self.assertEqual(lookup.canonical_media_id, "269")
        self.assertEqual(lookup.payload["root_media_id"], "269")

    def test_load_payload_for_media_alias_hit_loads_canonical_payload(self):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223", "269"]
        anime_franchise_cache.save_payload("223", payload)
        anime_franchise_cache.replace_aliases("223", payload)

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertTrue(lookup.alias_hit)
        self.assertEqual(lookup.requested_media_id, "269")
        self.assertEqual(lookup.canonical_media_id, "223")
        self.assertEqual(lookup.payload["root_media_id"], "223")

    def test_load_payload_for_media_deletes_broken_alias_without_payload(self):
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertIsNone(lookup.payload)
        self.assertFalse(lookup.alias_hit)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    def test_load_payload_for_media_deletes_alias_when_payload_does_not_cover_request(
        self,
    ):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223"]
        anime_franchise_cache.save_payload("223", payload)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertIsNone(lookup.payload)
        self.assertFalse(lookup.alias_hit)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    def test_load_payload_for_media_deletes_alias_with_mismatched_aliased_media_id(
        self,
    ):
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="999",
            ),
        )

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertIsNone(lookup.payload)
        self.assertFalse(lookup.alias_hit)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    def test_load_payload_for_media_ignores_alias_when_disabled(self):
        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        anime_franchise_cache.save_payload(canonical_id, prepared)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_payload_for_media("269")

        self.assertIsNone(lookup.payload)
        self.assertFalse(lookup.alias_hit)

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
