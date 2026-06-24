# ruff: noqa: D101,D102
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.services import anime_franchise_cache
from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService


@override_settings(
    ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=True,
    ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION=1,
    ANIME_FRANCHISE_CACHE_TTL_DAYS=365,
)
class AnimeFranchiseCacheBuildServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def make_payload(self, *, root_id="223", alias_ids=None):
        alias_ids = alias_ids or [root_id]
        entries = [
            {
                "media_id": media_id,
                "source": "mal",
                "media_type": "anime",
                "title": f"Anime {media_id}",
            }
            for media_id in alias_ids
        ]
        return {
            "schema_version": 1,
            "root_media_id": root_id,
            "canonical_root_media_id": root_id,
            "display_title": f"Anime {root_id}",
            "series": {"key": "series", "title": "Series", "entries": entries},
            "sections": [],
            "aliasable_media_ids": list(alias_ids),
            "covered_media_ids": list(alias_ids),
            "truncated": False,
            "node_count": len(alias_ids),
        }

    def make_global_payload(self, *, media_id="223", alias_ids=None, truncated=False):
        payload = self.make_payload(root_id=media_id, alias_ids=alias_ids or [media_id])
        payload.update(
            {
                "payload_role": anime_franchise_cache.PAYLOAD_ROLE_GLOBAL,
                "payload_kind": anime_franchise_cache.PAYLOAD_KIND_CANONICAL_FRANCHISE,
                "build_seed_media_id": media_id,
                "truncated": truncated,
            }
        )
        return payload

    def make_scoped_payload(
        self,
        *,
        seed_id="269",
        canonical_id="223",
        title="Scoped",
        entry_ids=None,
    ):
        payload = self.make_payload(root_id=seed_id, alias_ids=entry_ids or [seed_id])
        payload.update(
            {
                "display_title": title,
                "payload_role": anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED,
                "detail_payload_kind": (
                    anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT
                ),
                "rule_key": "non_tv_seed_to_tv_context_v1",
                "build_seed_media_id": seed_id,
                "global_canonical_root_media_id": canonical_id,
            }
        )
        return payload

    def make_build_session(self, *, canonical_id="223", truncated=False):
        snapshot = SimpleNamespace(canonical_root_media_id=str(canonical_id))
        graph_builder = SimpleNamespace(
            truncated=truncated,
            truncation_reason="limit" if truncated else "",
            node_count=2,
        )
        snapshot_service = Mock()
        snapshot_service.graph_builder = graph_builder
        snapshot_service.build.return_value = snapshot
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service
        return build_session, snapshot

    def save_global(self, media_id="223", *, alias_ids=None, truncated=False):
        payload = self.make_global_payload(
            media_id=media_id,
            alias_ids=alias_ids or [media_id],
            truncated=truncated,
        )
        anime_franchise_cache.save_global_payload(
            media_id,
            payload,
            meta=anime_franchise_cache.build_payload_meta(
                payload,
                node_count=len(payload["covered_media_ids"]),
                truncated=truncated,
            ),
        )
        return payload

    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_canonical_build_non_truncated_saves_global_and_creates_aliases(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        build_session, snapshot = self.make_build_session(canonical_id="223")
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="223", alias_ids=["223", "269"]
        )
        mock_build_detail_scoped_payload.return_value = None

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save("223")

        self.assertTrue(result["built"])
        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("223"))
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("269"))
        )
        mock_build_detail_scoped_payload.assert_called_once_with(
            snapshot, seed_media_id="223"
        )

    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_canonical_build_truncated_deletes_previous_aliases(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        payload = self.save_global("223", alias_ids=["223", "269"])
        anime_franchise_cache.replace_aliases("223", payload)
        build_session, _snapshot = self.make_build_session(
            canonical_id="223", truncated=True
        )
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="223", alias_ids=["223", "269"]
        )
        mock_build_detail_scoped_payload.return_value = None

        AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
            "223"
        )

        self.assertIsNotNone(
            cache.get(anime_franchise_cache.get_global_payload_key("223"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_index_key("223")))

    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_non_canonical_build_never_saves_global_seed_and_saves_scoped(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        self.save_global("223", alias_ids=["223", "269"])
        legacy_seed = self.make_global_payload(media_id="269", alias_ids=["269"])
        anime_franchise_cache.save_global_payload("269", legacy_seed)
        build_session, _snapshot = self.make_build_session(canonical_id="223")
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="223", alias_ids=["223", "269"]
        )
        mock_build_detail_scoped_payload.return_value = self.make_scoped_payload(
            canonical_id="223",
            entry_ids=["269", "270"],
        )

        AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
            "269"
        )

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("269"))
        )
        scoped_lookup = anime_franchise_cache.load_scoped_payload("269")
        self.assertIsNotNone(scoped_lookup)
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        detail_lookup = anime_franchise_cache.load_detail_franchise_payload("269")
        self.assertEqual(detail_lookup.hit_kind, "scoped_exact")

    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_non_canonical_build_skips_poor_scoped_when_alias_global_is_richer(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        canonical = self.make_global_payload(media_id="34161", alias_ids=["34161"])
        canonical["aliasable_media_ids"] = ["34161", "34428"]
        canonical["covered_media_ids"] = ["34161", "34428", "29803"]
        canonical["series"]["entries"] = [
            {
                "media_id": "29803",
                "source": "mal",
                "media_type": "anime",
                "anime_media_type": "tv",
                "title": "Overlord",
            }
        ]
        canonical["sections"] = [
            {
                "key": "continuity_extras",
                "title": "Main Story Extras",
                "visible_in_ui": True,
                "entries": [
                    {
                        "media_id": "34161",
                        "source": "mal",
                        "media_type": "anime",
                        "anime_media_type": "movie",
                        "title": "Overlord Movie 1",
                    },
                    {
                        "media_id": "34428",
                        "source": "mal",
                        "media_type": "anime",
                        "anime_media_type": "movie",
                        "title": "Overlord Movie 2",
                    },
                ],
            }
        ]
        anime_franchise_cache.save_global_payload("34161", canonical)
        anime_franchise_cache.replace_aliases("34161", canonical)
        anime_franchise_cache.save_scoped_payload(
            "34428",
            self.make_scoped_payload(seed_id="34428", canonical_id="34161"),
        )
        build_session, _snapshot = self.make_build_session(canonical_id="34161")
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="34161", alias_ids=["34161", "34428"]
        )
        mock_build_detail_scoped_payload.return_value = self.make_scoped_payload(
            seed_id="34428",
            canonical_id="34161",
        )

        AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
            "34428"
        )

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("34428"))
        )
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_scoped_payload_key("34428"))
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("34428")))
        lookup = anime_franchise_cache.load_detail_franchise_payload("34428")
        self.assertEqual(lookup.hit_kind, "alias")
        self.assertEqual(lookup.canonical_media_id, "34161")

    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_non_canonical_build_without_scoped_deletes_old_scoped_and_keeps_alias(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        canonical = self.save_global("223", alias_ids=["223", "269"])
        anime_franchise_cache.replace_aliases("223", canonical)
        anime_franchise_cache.save_scoped_payload(
            "269", self.make_scoped_payload(seed_id="269")
        )
        build_session, _snapshot = self.make_build_session(canonical_id="223")
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="223", alias_ids=["223", "269"]
        )
        mock_build_detail_scoped_payload.return_value = None

        AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
            "269"
        )

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_scoped_payload_key("269"))
        )
        self.assertIsNotNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        lookup = anime_franchise_cache.load_detail_franchise_payload("269")
        self.assertEqual(lookup.hit_kind, "alias")

    @override_settings(ANIME_FRANCHISE_CACHE_ALIASES_ENABLED=False)
    @patch(
        "app.services.anime_franchise_cache_builder.build_detail_scoped_payload_from_snapshot"
    )
    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    @patch("app.services.anime_franchise_cache_builder.serialize_franchise_payload")
    def test_aliases_disabled_does_not_create_alias_or_global_seed(
        self,
        mock_serialize,
        mock_pipeline_class,
        mock_build_detail_scoped_payload,
    ):
        build_session, _snapshot = self.make_build_session(canonical_id="223")
        mock_pipeline_class.return_value.run.return_value = object()
        mock_serialize.return_value = self.make_payload(
            root_id="223", alias_ids=["223", "269"]
        )
        mock_build_detail_scoped_payload.return_value = None

        AnimeFranchiseCacheBuildService(build_session=build_session).build_and_save(
            "269"
        )

        self.assertIsNone(
            cache.get(anime_franchise_cache.get_global_payload_key("269"))
        )
        self.assertIsNone(cache.get(anime_franchise_cache.get_alias_key("269")))
        self.assertIsNone(
            cache.get(anime_franchise_cache.get_scoped_payload_key("269"))
        )

    @patch("app.services.anime_franchise_cache_builder.AnimeFranchiseUiPipeline")
    def test_build_and_save_marks_error_on_failure(self, mock_pipeline_class):
        snapshot_service = Mock()
        snapshot_service.graph_builder = SimpleNamespace(
            truncated=False,
            truncation_reason="",
            node_count=1,
        )
        snapshot_service.build.side_effect = RuntimeError("boom")
        build_session = Mock()
        build_session.snapshot_service.return_value = snapshot_service

        result = AnimeFranchiseCacheBuildService(
            build_session=build_session
        ).build_and_save("100")

        build_meta = anime_franchise_cache.load_build_meta("100")
        self.assertFalse(result["built"])
        self.assertEqual(result["error"], "boom")
        self.assertEqual(build_meta["last_error_message"], "boom")
        mock_pipeline_class.return_value.run.assert_not_called()
