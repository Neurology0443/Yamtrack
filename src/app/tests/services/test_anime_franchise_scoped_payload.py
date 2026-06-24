# ruff: noqa: D101,D102
import json
from datetime import date

from django.test import SimpleTestCase, override_settings

from app.services import anime_franchise_cache
from app.services.anime_franchise_scoped_payload import (
    build_detail_scoped_payload_from_snapshot,
    should_prefer_alias_global_payload,
)
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


@override_settings(ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION=1)
class AnimeFranchiseScopedPayloadTests(SimpleTestCase):
    def _node(
        self,
        media_id,
        *,
        media_type="tv",
        title=None,
        image="img",
        start_date=date(2020, 1, 1),
        relations=None,
        runtime_minutes=24,
        episode_count=12,
    ):
        return AnimeNode(
            str(media_id),
            title or f"Title {media_id}",
            "mal",
            media_type,
            image,
            start_date,
            relations or [],
            runtime_minutes,
            episode_count,
        )

    def _snapshot(self, *, seed=None, nodes=None, relations=None, canonical="11757"):
        seed = seed or self._node("40489", media_type="tv_special")
        nodes = nodes or {seed.media_id: seed}
        root_node = nodes.get(seed.media_id, seed)
        return AnimeFranchiseSnapshot(
            root_node=root_node,
            nodes_by_media_id=nodes,
            all_normalized_relations=relations or [],
            continuity_component=list(nodes.values()),
            series_line=[],
            direct_anchors=[],
            direct_candidates=[],
            has_series_line=False,
            fallback_anchor_media_id=root_node.media_id,
            canonical_root_media_id=canonical,
        )

    def test_builds_scoped_payload_for_special_seed_with_story_and_sequel(self):
        relations = [
            AnimeRelation("40489", "36474", "full_story"),
            AnimeRelation("40489", "39597", "sequel"),
        ]
        seed = self._node("40489", media_type="tv_special", relations=relations)
        nodes = {
            "40489": seed,
            "36474": self._node("36474", title="Main Story"),
            "39597": self._node("39597", title="Sequel"),
        }

        payload = build_detail_scoped_payload_from_snapshot(
            self._snapshot(seed=seed, nodes=nodes, relations=relations),
            seed_media_id="40489",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["root_media_id"], "40489")
        self.assertEqual(payload["canonical_root_media_id"], "40489")
        self.assertEqual(payload["series"]["entries"], [])
        self.assertEqual(
            payload["payload_role"], anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED
        )
        self.assertEqual(
            payload["detail_payload_kind"],
            anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT,
        )
        self.assertEqual(payload["rule_key"], "non_tv_seed_to_tv_context_v1")
        related_ids = [entry["media_id"] for entry in payload["sections"][0]["entries"]]
        self.assertEqual(related_ids, ["36474", "39597"])
        self.assertTrue(anime_franchise_cache.is_valid_scoped_payload(payload))

    def test_returns_none_for_canonical_seed(self):
        seed = self._node("11757", media_type="tv_special")
        snapshot = self._snapshot(seed=seed, nodes={"11757": seed}, canonical="11757")

        payload = build_detail_scoped_payload_from_snapshot(
            snapshot,
            seed_media_id="11757",
        )

        self.assertIsNone(payload)

    def test_returns_none_for_tv_seed(self):
        seed = self._node("40489", media_type="tv")
        snapshot = self._snapshot(seed=seed, nodes={"40489": seed})

        payload = build_detail_scoped_payload_from_snapshot(
            snapshot,
            seed_media_id="40489",
        )

        self.assertIsNone(payload)

    def test_ignores_non_tv_targets(self):
        relation = AnimeRelation("40489", "50000", "full_story")
        seed = self._node("40489", media_type="tv_special", relations=[relation])
        nodes = {
            "40489": seed,
            "50000": self._node("50000", media_type="movie"),
        }

        payload = build_detail_scoped_payload_from_snapshot(
            self._snapshot(seed=seed, nodes=nodes, relations=[relation]),
            seed_media_id="40489",
        )

        self.assertIsNone(payload)

    def test_deduplicates_targets_preserving_first_relation(self):
        relations = [
            AnimeRelation("40489", "36474", "full_story"),
            AnimeRelation("40489", "36474", "sequel"),
        ]
        seed = self._node("40489", media_type="tv_special", relations=relations)
        nodes = {
            "40489": seed,
            "36474": self._node("36474", title="Main Story"),
        }

        payload = build_detail_scoped_payload_from_snapshot(
            self._snapshot(seed=seed, nodes=nodes, relations=relations),
            seed_media_id="40489",
        )

        entries = payload["sections"][0]["entries"]
        self.assertEqual([entry["media_id"] for entry in entries], ["36474"])
        self.assertEqual(entries[0]["relation_type"], "full_story")

    def test_payload_is_json_safe_and_valid(self):
        relation = AnimeRelation("40489", "36474", "prequel")
        seed = self._node("40489", media_type="tv_special", relations=[relation])
        nodes = {
            "40489": seed,
            "36474": self._node("36474", title="Prequel", start_date=date(2019, 1, 1)),
        }

        payload = build_detail_scoped_payload_from_snapshot(
            self._snapshot(seed=seed, nodes=nodes, relations=[relation]),
            seed_media_id="40489",
        )

        json.dumps(payload)
        self.assertTrue(anime_franchise_cache.is_valid_scoped_payload(payload))
        entry = payload["sections"][0]["entries"][0]
        self.assertEqual(entry["start_date"], "2019-01-01")
        self.assertEqual(entry["runtime_minutes"], 24)
        self.assertEqual(entry["episode_count"], 12)

    def _global_payload_for_alias_preference(self):
        return {
            "schema_version": 1,
            "root_media_id": "34161",
            "canonical_root_media_id": "34161",
            "display_title": "Overlord Movies",
            "payload_role": anime_franchise_cache.PAYLOAD_ROLE_GLOBAL,
            "payload_kind": anime_franchise_cache.PAYLOAD_KIND_CANONICAL_FRANCHISE,
            "build_seed_media_id": "34161",
            "aliasable_media_ids": ["34161", "34428"],
            "covered_media_ids": ["34161", "34428", "29803"],
            "series": {
                "key": "series",
                "title": "Series",
                "entries": [
                    {
                        "media_id": "29803",
                        "source": "mal",
                        "media_type": "anime",
                        "anime_media_type": "tv",
                        "title": "Overlord",
                    },
                ],
            },
            "sections": [
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
                },
            ],
        }

    def _scoped_payload_for_alias_preference(self):
        return {
            "schema_version": 1,
            "root_media_id": "34428",
            "canonical_root_media_id": "34428",
            "display_title": "Overlord Movie 2",
            "payload_role": anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED,
            "detail_payload_kind": (
                anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT
            ),
            "rule_key": "non_tv_seed_to_tv_context_v1",
            "global_canonical_root_media_id": "34161",
            "build_seed_media_id": "34428",
            "series": {"key": "series", "title": "Series", "entries": []},
            "sections": [
                {
                    "key": "related_series",
                    "title": "Related Series",
                    "visible_in_ui": True,
                    "entries": [
                        {
                            "media_id": "29803",
                            "source": "mal",
                            "media_type": "anime",
                            "anime_media_type": "tv",
                            "title": "Overlord",
                        },
                    ],
                },
            ],
        }

    def test_prefers_alias_global_when_canonical_has_richer_seed_context(self):
        self.assertTrue(
            should_prefer_alias_global_payload(
                seed_media_id="34428",
                canonical_payload=self._global_payload_for_alias_preference(),
                scoped_payload=self._scoped_payload_for_alias_preference(),
            )
        )

    def test_does_not_prefer_alias_global_when_seed_is_not_aliasable(self):
        canonical_payload = self._global_payload_for_alias_preference()
        canonical_payload["aliasable_media_ids"] = ["34161"]

        self.assertFalse(
            should_prefer_alias_global_payload(
                seed_media_id="34428",
                canonical_payload=canonical_payload,
                scoped_payload=self._scoped_payload_for_alias_preference(),
            )
        )

    def test_does_not_prefer_alias_global_when_scoped_is_equally_rich(self):
        scoped_payload = self._scoped_payload_for_alias_preference()
        scoped_payload["sections"][0]["entries"].extend(
            [
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
            ]
        )

        self.assertFalse(
            should_prefer_alias_global_payload(
                seed_media_id="34428",
                canonical_payload=self._global_payload_for_alias_preference(),
                scoped_payload=scoped_payload,
            )
        )
