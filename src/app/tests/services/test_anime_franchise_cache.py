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

    def make_global_payload(
        self, payload=None, *, media_id="100", build_seed_media_id=None
    ):
        payload = deepcopy(payload or self.payload)
        payload.setdefault(
            "schema_version",
            1,
        )
        payload.setdefault("root_media_id", str(media_id))
        payload.setdefault("canonical_root_media_id", str(media_id))
        payload.setdefault("display_title", "Root")
        payload["payload_role"] = anime_franchise_cache.PAYLOAD_ROLE_GLOBAL
        payload["payload_kind"] = anime_franchise_cache.PAYLOAD_KIND_CANONICAL_FRANCHISE
        payload["build_seed_media_id"] = str(build_seed_media_id or media_id)
        return payload

    def make_scoped_payload(
        self,
        payload=None,
        *,
        seed_id="40489",
        canonical_id="11757",
        detail_payload_kind=anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT,
        rule_key="non_tv_seed_to_tv_context_v1",
    ):
        payload = deepcopy(payload or self.payload)
        payload.setdefault("schema_version", 1)
        payload["root_media_id"] = str(seed_id)
        payload["canonical_root_media_id"] = str(seed_id)
        payload["payload_role"] = anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED
        payload["detail_payload_kind"] = detail_payload_kind
        payload["rule_key"] = rule_key
        payload["build_seed_media_id"] = str(seed_id)
        payload["global_canonical_root_media_id"] = str(canonical_id)
        return payload

    def save_test_global_payload(self, media_id, payload=None, **meta_kwargs):
        prepared = self.make_global_payload(payload, media_id=media_id)
        if isinstance(payload, dict):
            payload.clear()
            payload.update(prepared)
        payload = prepared
        meta = anime_franchise_cache.build_payload_meta(payload, **meta_kwargs)
        return anime_franchise_cache.save_global_payload(media_id, payload, meta=meta)

    def save_test_scoped_payload(self, media_id, payload=None, **meta_kwargs):
        payload = self.make_scoped_payload(payload, seed_id=media_id)
        meta = anime_franchise_cache.build_payload_meta(payload, **meta_kwargs)
        return anime_franchise_cache.save_scoped_payload(media_id, payload, meta=meta)

    def unwrap_lookup(self, lookup):
        self.assertIsNotNone(lookup)
        return lookup.payload, lookup.meta

    def _assert_no_direct_payload_alias_conflict(self, media_ids):
        for media_id in media_ids:
            direct = cache.get(anime_franchise_cache.get_global_payload_key(media_id))
            alias = cache.get(anime_franchise_cache.get_alias_key(media_id))
            self.assertFalse(direct and alias, media_id)

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

    def _payload_with_special_seed_candidate(self):
        return {
            "schema_version": 1,
            "root_media_id": "40489",
            "display_title": "Canonical Series",
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "11757",
                        "source": "mal",
                        "media_type": "anime",
                        "title": "Canonical Series",
                    },
                ],
            },
            "sections": [
                {
                    "key": "specials",
                    "title": "Specials",
                    "entries": [
                        {
                            "media_id": "40489",
                            "source": "mal",
                            "media_type": "anime",
                            "title": "Special Entry",
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

    def test_related_parent_story_target_is_not_aliasable(self):
        payload = {
            "series": {"entries": []},
            "sections": [
                {
                    "key": "continuity_extras",
                    "entries": [
                        {"media_id": media_id}
                        for media_id in [
                            "33142",
                            "33569",
                            "42364",
                            "60012",
                            "63830",
                        ]
                    ],
                },
                {
                    "key": "related_series",
                    "entries": [{"media_id": "99999"}],
                },
            ],
        }

        self.assertNotIn(
            "99999",
            anime_franchise_cache.extract_aliasable_media_ids(payload),
        )
        self.assertIn("99999", anime_franchise_cache.extract_payload_media_ids(payload))

    def test_related_series_root_story_parent_is_covered_but_not_aliasable(self):
        payload = {
            "series": {"entries": []},
            "sections": [
                {
                    "key": "continuity_extras",
                    "entries": [{"media_id": "27891"}],
                },
                {
                    "key": "specials",
                    "entries": [{"media_id": "27891"}],
                },
                {
                    "key": "related_series",
                    "entries": [{"media_id": "100"}],
                },
            ],
        }

        self.assertIn("100", anime_franchise_cache.extract_payload_media_ids(payload))
        self.assertNotIn(
            "100",
            anime_franchise_cache.extract_aliasable_media_ids(payload),
        )

    def test_determine_canonical_media_id_from_series_line(self):
        self.assertEqual(
            anime_franchise_cache.determine_canonical_media_id(
                self._dragon_ball_payload(),
                "269",
            ),
            "223",
        )

    def test_determine_canonical_media_id_prefers_series_over_canonical_root(
        self,
    ):
        payload = {
            "series": {"entries": [{"media_id": "100"}]},
            "canonical_root_media_id": "999",
        }

        self.assertEqual(
            anime_franchise_cache.determine_canonical_media_id(payload, "33569"),
            "100",
        )

    def test_determine_canonical_media_id_uses_canonical_root_without_series(self):
        payload = {
            "series": {"entries": []},
            "canonical_root_media_id": "33142",
        }

        self.assertEqual(
            anime_franchise_cache.determine_canonical_media_id(payload, "33569"),
            "33142",
        )

    def test_determine_canonical_media_id_falls_back_for_legacy_payload(self):
        payload = {"series": {"entries": []}}

        self.assertEqual(
            anime_franchise_cache.determine_canonical_media_id(payload, "33569"),
            "33569",
        )

    def test_prepare_payload_for_aliasing_uses_mini_franchise_canonical_root(self):
        payload = {
            "schema_version": 1,
            "root_media_id": "33569",
            "canonical_root_media_id": "33142",
            "display_title": "Re:Petit",
            "series": {"key": "series", "title": "Series", "entries": []},
            "sections": [
                {
                    "key": "continuity_extras",
                    "title": "Main Story Extras",
                    "entries": [
                        {
                            "media_id": media_id,
                            "source": "mal",
                            "media_type": "anime",
                            "title": title,
                        }
                        for media_id, title in [
                            ("33569", "Re:Petit"),
                            ("42364", "Break Time 2"),
                            ("60012", "Break Time 3"),
                            ("63830", "Break Time 4"),
                        ]
                    ],
                }
            ],
        }

        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="33569",
                truncated=False,
                aliases_enabled=True,
            )
        )

        expected_ids = {"33142", "33569", "42364", "60012", "63830"}
        self.assertEqual(canonical_id, "33142")
        self.assertEqual(prepared["root_media_id"], "33142")
        self.assertEqual(prepared["canonical_root_media_id"], "33142")
        self.assertEqual(set(prepared["aliasable_media_ids"]), expected_ids)
        self.assertEqual(aliasable_ids, expected_ids)
        self.assertEqual(set(prepared["covered_media_ids"]), expected_ids)

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
        payload = self._payload_with_special_seed_candidate()

        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="40489",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertEqual(canonical_id, "11757")
        self.assertIn("40489", prepared["covered_media_ids"])
        self.assertNotIn("40489", prepared["aliasable_media_ids"])
        self.assertNotIn("40489", aliasable_ids)

    def test_prepare_payload_for_aliasing_does_not_alias_passive_special(self):
        payload = self._payload_with_special_seed_candidate()

        prepared, canonical_id, aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="11757",
                truncated=False,
                aliases_enabled=True,
            )
        )

        self.assertEqual(canonical_id, "11757")
        self.assertIn("40489", prepared["covered_media_ids"])
        self.assertNotIn("40489", prepared["aliasable_media_ids"])
        self.assertNotIn("40489", aliasable_ids)

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

    def test_replace_aliases_creates_lightweight_records_after_save_global_payload(
        self,
    ):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223", "813", "269"]
        self.save_test_global_payload("223", payload)

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
                build_seed_media_id="999",
                truncated=False,
                aliases_enabled=True,
            )
        )
        self.save_test_global_payload(canonical_id, prepared)

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
        self.save_test_global_payload(canonical_id, prepared)
        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        alias = cache.get(anime_franchise_cache.get_alias_key("225"))
        self.assertIsNotNone(alias)
        self.assertEqual(alias["canonical_media_id"], "223")

        lookup = anime_franchise_cache.load_detail_franchise_payload("225")
        self.assertEqual(lookup.hit_kind, "alias")
        self.assertEqual(lookup.canonical_media_id, "223")
        self.assertEqual(lookup.payload["root_media_id"], "223")

    def test_replace_aliases_preserves_direct_payload_for_non_aliasable_special_seed(
        self,
    ):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "999"
        direct_payload["display_title"] = "Dragon Ball Special"
        direct_payload["series"]["entries"][0]["media_id"] = "999"
        self.save_test_global_payload("999", direct_payload)

        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        self.save_test_global_payload(canonical_id, prepared)
        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("999")))
        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("999"))
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("999")
        self.assertEqual(lookup.hit_kind, "global_exact")
        self.assertEqual(lookup.canonical_media_id, "999")
        self.assertEqual(lookup.payload["root_media_id"], "999")

    def test_replace_aliases_deletes_stale_direct_payload_for_aliased_media_id(
        self,
    ):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["display_title"] = "Dragon Ball GT"
        direct_payload["series"]["entries"][0]["media_id"] = "269"
        self.save_test_global_payload("269", direct_payload)
        payload = self._dragon_ball_payload()
        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        self.save_test_global_payload(canonical_id, prepared)

        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("269"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_global_meta_key("269")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("223"))
        )
        lookup = anime_franchise_cache.load_detail_franchise_payload("269")
        self.assertEqual(lookup.hit_kind, "alias")
        self.assertEqual(lookup.canonical_media_id, canonical_id)
        self.assertEqual(lookup.payload["root_media_id"], canonical_id)
        self._assert_no_direct_payload_alias_conflict(["269"])

    def test_replace_aliases_does_not_create_self_alias_for_canonical_media_id(self):
        payload = self._dragon_ball_payload()
        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                payload,
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        prepared["aliasable_media_ids"] = [canonical_id, "269"]
        self.save_test_global_payload(canonical_id, prepared)

        anime_franchise_cache.replace_aliases(canonical_id, prepared)

        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key(canonical_id)))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self._assert_no_direct_payload_alias_conflict([canonical_id, "269"])

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

    def test_load_detail_franchise_payload_prefers_direct_payload_over_alias(self):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["display_title"] = "Dragon Ball GT"
        direct_payload["series"]["entries"][0]["media_id"] = "269"
        self.save_test_global_payload("269", direct_payload)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertEqual(lookup.hit_kind, "global_exact")
        self.assertEqual(lookup.canonical_media_id, "269")
        self.assertEqual(lookup.payload["root_media_id"], "269")

    def test_save_global_payload_deletes_stale_alias_and_updates_canonical_index(self):
        canonical_payload = self._dragon_ball_payload()
        canonical_payload["aliasable_media_ids"] = ["223", "269"]
        self.save_test_global_payload("223", canonical_payload)
        anime_franchise_cache.replace_aliases("223", canonical_payload)

        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["display_title"] = "Dragon Ball GT"
        direct_payload["series"]["entries"][0]["media_id"] = "269"

        self.save_test_global_payload("269", direct_payload)

        saved_payload = cache.get(anime_franchise_cache.get_global_payload_key("269"))
        self.assertTrue(anime_franchise_cache.is_valid_payload(saved_payload))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_index_key("223")))

    def test_save_global_payload_is_idempotent_without_existing_alias(self):
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "50360"
        direct_payload["series"]["entries"][0]["media_id"] = "50360"

        self.save_test_global_payload("50360", direct_payload)

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("50360"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("50360")))

    def test_invalid_payload_does_not_delete_existing_alias(self):
        alias = anime_franchise_cache._build_alias_record(
            canonical_media_id="223",
            aliased_media_id="269",
        )
        cache.set(anime_franchise_cache.get_alias_key("269"), alias)
        cache.set(
            anime_franchise_cache.get_alias_index_key("223"),
            ["269"],
        )
        invalid_payload = deepcopy(self.payload)
        invalid_payload["series"]["entries"] = {}

        with self.assertRaises(ValueError):
            self.save_test_global_payload("269", invalid_payload)

        self.assertEqual(
            cache.get(anime_franchise_cache.get_alias_key("269")),
            alias,
        )
        self.assertEqual(
            cache.get(anime_franchise_cache.get_alias_index_key("223")),
            ["269"],
        )

    def test_save_global_payload_deletes_malformed_alias_without_crashing(self):
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            {"bad": "alias"},
        )
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["series"]["entries"][0]["media_id"] = "269"

        self.save_test_global_payload("269", direct_payload)

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("269"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    def test_save_global_payload_preserves_other_canonical_aliases(self):
        for media_id in ("813", "269", "225"):
            cache.set(
                anime_franchise_cache.get_alias_key(media_id),
                anime_franchise_cache._build_alias_record(
                    canonical_media_id="223",
                    aliased_media_id=media_id,
                ),
            )
        cache.set(
            anime_franchise_cache.get_alias_index_key("223"),
            ["813", "269", "225"],
        )
        direct_payload = deepcopy(self.payload)
        direct_payload["root_media_id"] = "269"
        direct_payload["series"]["entries"][0]["media_id"] = "269"

        self.save_test_global_payload("269", direct_payload)

        self.assertEqual(
            cache.get(anime_franchise_cache.get_alias_index_key("223")),
            ["813", "225"],
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("813")))
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("225")))

    def test_load_detail_franchise_payload_alias_loads_canonical_payload(self):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223", "269"]
        self.save_test_global_payload("223", payload)
        anime_franchise_cache.replace_aliases("223", payload)

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertEqual(lookup.hit_kind, "alias")
        self.assertEqual(lookup.requested_media_id, "269")
        self.assertEqual(lookup.canonical_media_id, "223")
        self.assertEqual(lookup.payload["root_media_id"], "223")

    def test_load_detail_franchise_payload_deletes_broken_alias_without_payload(self):
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertIsNone(lookup)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self._assert_no_direct_payload_alias_conflict(["269"])

    def test_detail_resolver_deletes_alias_for_uncovered_target(
        self,
    ):
        payload = self._dragon_ball_payload()
        payload["aliasable_media_ids"] = ["223"]
        self.save_test_global_payload("223", payload)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertIsNone(lookup)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self._assert_no_direct_payload_alias_conflict(["269"])

    def test_detail_resolver_deletes_mismatched_alias(
        self,
    ):
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="999",
            ),
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertIsNone(lookup)
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    def test_load_detail_franchise_payload_ignores_alias_when_disabled(self):
        prepared, canonical_id, _aliasable_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                self._dragon_ball_payload(),
                build_seed_media_id="223",
                truncated=False,
                aliases_enabled=True,
            )
        )
        self.save_test_global_payload(canonical_id, prepared)
        cache.set(
            anime_franchise_cache.get_alias_key("269"),
            anime_franchise_cache._build_alias_record(
                canonical_media_id="223",
                aliased_media_id="269",
            ),
        )

        lookup = anime_franchise_cache.load_detail_franchise_payload("269")

        self.assertIsNone(lookup)

    def test_save_and_load_payload_updates_access_metadata(self):
        self.save_test_global_payload("100", self.payload, node_count=1)

        payload, meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        self.assertEqual(payload["root_media_id"], "100")
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(meta["node_count"], 1)

    def test_incompatible_schema_is_ignored_but_meta_is_returned(self):
        bad_payload = self.make_global_payload({**self.payload, "schema_version": 999})
        cache.set(anime_franchise_cache.get_global_payload_key("100"), bad_payload)

        lookup = anime_franchise_cache.load_global_payload("100")

        self.assertIsNone(lookup)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    def test_stale_payload_is_displayable_but_schedulable(self):
        stale_time = timezone.now() - timedelta(days=31)
        self.save_test_global_payload("100", self.payload, fetched_at=stale_time)
        payload, meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        self.assertIsNotNone(payload)
        self.assertFalse(anime_franchise_cache.is_fresh(meta))
        self.assertTrue(
            False
            if anime_franchise_cache.is_fresh(meta)
            else anime_franchise_cache.can_schedule_build(
                anime_franchise_cache.load_build_meta("100")
            ),
        )

    def test_missing_payload_returns_empty_meta(self):
        lookup = anime_franchise_cache.load_global_payload("404")
        payload = lookup.payload if lookup else None
        meta = anime_franchise_cache.normalize_meta(None)

        self.assertIsNone(payload)
        self.assertIsNone(meta["fetched_at"])

    def test_fresh_payload_with_has_payload_blocks_scheduling(self):
        self.save_test_global_payload("100", self.payload)
        _payload, meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        self.assertTrue(anime_franchise_cache.is_fresh(meta))
        self.assertFalse(
            False
            if anime_franchise_cache.is_fresh(meta)
            else anime_franchise_cache.can_schedule_build(
                anime_franchise_cache.load_build_meta("100")
            ),
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
        self.save_test_global_payload("100", self.payload)
        before_payload, before_meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        meta = anime_franchise_cache.mark_error("100", "boom")
        after_payload, _after_meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        self.assertEqual(after_payload, before_payload)
        self.assertEqual(_after_meta["fetched_at"], before_meta["fetched_at"])
        self.assertEqual(_after_meta["last_success_at"], before_meta["last_success_at"])
        self.assertEqual(_after_meta["node_count"], before_meta["node_count"])
        self.assertEqual(_after_meta["truncated"], before_meta["truncated"])
        self.assertEqual(
            _after_meta["truncation_reason"], before_meta["truncation_reason"]
        )
        self.assertEqual(meta["last_error_message"], "boom")

    def test_normalize_meta_empty_dict_keeps_required_defaults(self):
        meta = anime_franchise_cache.normalize_meta({})

        self.assertEqual(
            meta["schema_version"],
            1,
        )
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
                    self.save_test_global_payload("bad", payload)

    def test_save_global_payload_rejects_non_json_safe_payload(self):
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
            self.save_test_global_payload("100", payload)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    def test_save_global_payload_rejects_user_specific_keys(self):
        for forbidden_key in ("media", "item", "progress", "status", "user_id", "html"):
            payload = deepcopy(self.payload)
            payload["series"]["entries"][0][forbidden_key] = "bad"

            with self.subTest(forbidden_key=forbidden_key):
                with self.assertRaises(ValueError):
                    self.save_test_global_payload("100", payload)
                self.assertIsNone(
                    cache.get(anime_franchise_cache.get_global_payload_key("100"))
                )

    def test_invalid_payload_load_returns_none_and_normalized_meta(self):
        cache.set(
            anime_franchise_cache.get_global_payload_key("100"),
            {"schema_version": 1, "root_media_id": "100"},
        )

        lookup = anime_franchise_cache.load_global_payload("100")

        self.assertIsNone(lookup)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    def test_normalize_meta_with_invalid_node_count_falls_back_to_zero(self):
        meta = anime_franchise_cache.normalize_meta({"node_count": "abc"})

        self.assertEqual(meta["node_count"], 0)
        self.assertEqual(meta["schema_version"], 1)

    def test_load_payload_with_corrupt_meta_node_count_does_not_crash(self):
        self.save_test_global_payload("100", self.payload)
        meta = anime_franchise_cache.normalize_meta(
            cache.get(anime_franchise_cache.get_global_meta_key("100")),
        )
        meta["node_count"] = "abc"
        cache.set(anime_franchise_cache.get_global_meta_key("100"), meta)

        payload, loaded_meta = self.unwrap_lookup(
            anime_franchise_cache.load_global_payload("100")
        )

        self.assertIsNotNone(payload)
        self.assertEqual(loaded_meta["node_count"], 0)

    def test_load_payload_rejects_cached_payload_with_user_specific_keys(self):
        payload = self.make_global_payload()
        payload["series"]["entries"][0]["progress"] = 4
        cache.set(anime_franchise_cache.get_global_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_global_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        lookup = anime_franchise_cache.load_global_payload("100")

        self.assertIsNone(lookup)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    def test_load_payload_rejects_cached_section_payload_with_user_specific_keys(self):
        payload = self.make_global_payload()
        payload["sections"][0]["entries"][0]["media"] = {"id": 1}
        cache.set(anime_franchise_cache.get_global_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_global_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        lookup = anime_franchise_cache.load_global_payload("100")

        self.assertIsNone(lookup)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    def test_load_payload_rejects_cached_non_json_safe_payload(self):
        payload = self.make_global_payload()
        payload["series"]["entries"][0]["bad"] = object()
        cache.set(anime_franchise_cache.get_global_payload_key("100"), payload)
        cache.set(
            anime_franchise_cache.get_global_meta_key("100"),
            anime_franchise_cache.default_meta(),
        )

        lookup = anime_franchise_cache.load_global_payload("100")

        self.assertIsNone(lookup)
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("100"))
        )

    @patch("app.tasks.build_mal_anime_franchise_payload.delay")
    def test_queue_lock_prevents_duplicate_scheduling(self, mock_delay):
        self.assertTrue(anime_franchise_cache.maybe_schedule_build("100"))
        self.assertFalse(anime_franchise_cache.maybe_schedule_build("100"))

        mock_delay.assert_called_once_with("100")

    def test_recent_error_respects_retry_cooldown(self):
        meta = anime_franchise_cache.mark_error("100", "boom")

        self.assertFalse(anime_franchise_cache.can_schedule_build(meta))
