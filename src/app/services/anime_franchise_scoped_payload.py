"""Build detail-scoped MAL anime franchise payloads for non-canonical seeds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Callable

from app.services import anime_franchise_cache

DISPLAYABLE_LOCAL_RELATIONS = {"full_story", "sequel", "prequel"}


@dataclass(frozen=True)
class DetailPayloadRule:
    """Rule that can build a detail-scoped payload from a snapshot."""

    rule_key: str
    detail_payload_kind: str
    priority: int
    build: Callable[[object, str], dict | None]


def _json_safe_date(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _entry_from_node(target_node, *, relation, seed_media_id: str) -> dict:
    entry = {
        "media_id": str(target_node.media_id),
        "source": target_node.source,
        "media_type": "anime",
        "anime_media_type": target_node.media_type,
        "title": target_node.title,
        "relation_type": relation.relation_type,
        "relation_source_media_id": seed_media_id,
        "linked_root_media_id": seed_media_id,
    }

    if target_node.image is not None:
        entry["image"] = target_node.image
    if target_node.start_date is not None:
        entry["start_date"] = _json_safe_date(target_node.start_date)
    if target_node.runtime_minutes is not None:
        entry["runtime_minutes"] = target_node.runtime_minutes
    if target_node.episode_count is not None:
        entry["episode_count"] = target_node.episode_count

    return entry


def _build_non_tv_seed_to_tv_context(
    snapshot,
    *,
    seed_media_id: str,
) -> dict | None:
    """Return seed context for a non-TV seed using snapshot data only."""
    seed_media_id = str(seed_media_id)
    if seed_media_id == str(snapshot.canonical_root_media_id):
        return None

    seed_node = snapshot.nodes_by_media_id.get(seed_media_id)
    if seed_node is None or seed_node.media_type == "tv":
        return None

    entries = []
    seen_targets: set[str] = set()
    for relation in snapshot.all_normalized_relations:
        target_media_id = str(relation.target_media_id)
        if str(relation.source_media_id) != seed_media_id:
            continue
        if relation.relation_type not in DISPLAYABLE_LOCAL_RELATIONS:
            continue
        if target_media_id == seed_media_id or target_media_id in seen_targets:
            continue

        target_node = snapshot.nodes_by_media_id.get(target_media_id)
        if target_node is None or target_node.media_type != "tv":
            continue

        seen_targets.add(target_media_id)
        entries.append(
            _entry_from_node(
                target_node,
                relation=relation,
                seed_media_id=seed_media_id,
            ),
        )

    if not entries:
        return None

    return {
        "schema_version": settings.ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION,
        "root_media_id": seed_media_id,
        "canonical_root_media_id": seed_media_id,
        "display_title": seed_node.title,
        "series": {
            "key": "series_line",
            "title": "Series",
            "entries": [],
        },
        "payload_role": anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED,
        "detail_payload_kind": anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT,
        "rule_key": "non_tv_seed_to_tv_context_v1",
        "global_canonical_root_media_id": str(snapshot.canonical_root_media_id),
        "build_seed_media_id": seed_media_id,
        "sections": [
            {
                "key": "related_series",
                "title": "Related Series",
                "entries": entries,
                "visible_in_ui": True,
                "hidden_if_empty": True,
            },
        ],
    }


DETAIL_PAYLOAD_RULES = (
    DetailPayloadRule(
        rule_key="non_tv_seed_to_tv_context_v1",
        detail_payload_kind=anime_franchise_cache.DETAIL_PAYLOAD_KIND_SEED_CONTEXT,
        priority=10,
        build=lambda snapshot, seed_media_id: _build_non_tv_seed_to_tv_context(
            snapshot,
            seed_media_id=seed_media_id,
        ),
    ),
)


def build_detail_scoped_payload_from_snapshot(
    snapshot, *, seed_media_id: str
) -> dict | None:
    """Build the first valid detail-scoped payload from ordered rules."""
    for rule in sorted(DETAIL_PAYLOAD_RULES, key=lambda item: item.priority):
        payload = rule.build(snapshot, str(seed_media_id))
        if payload is None:
            continue
        payload = dict(payload)
        payload.setdefault(
            "payload_role", anime_franchise_cache.PAYLOAD_ROLE_DETAIL_SCOPED
        )
        payload.setdefault("detail_payload_kind", rule.detail_payload_kind)
        payload.setdefault("rule_key", rule.rule_key)
        payload.setdefault("build_seed_media_id", str(seed_media_id))
        payload.setdefault(
            "global_canonical_root_media_id", str(snapshot.canonical_root_media_id)
        )
        if anime_franchise_cache.is_valid_scoped_payload(payload):
            anime_franchise_cache.assert_json_safe_payload(payload)
            return payload
    return None
