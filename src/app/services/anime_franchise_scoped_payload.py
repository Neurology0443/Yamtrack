"""Build detail-scoped MAL anime franchise payloads for non-canonical seeds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Callable

from app.services import anime_franchise_cache

DISPLAYABLE_LOCAL_RELATIONS = {"full_story", "sequel", "prequel"}
IGNORED_SECTION_KEYS = {"ignored"}
RICH_LOCAL_SECTION_KEYS = {"continuity_extras"}


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


def _entry_media_id(entry: Mapping[str, Any]) -> str | None:
    media_id = entry.get("media_id")
    if media_id in (None, ""):
        return None
    return str(media_id)


def _is_non_tv_entry(entry: Mapping[str, Any]) -> bool:
    media_type = entry.get("anime_media_type") or entry.get("media_type")
    return str(media_type).lower() not in {"", "anime", "tv"}


def _displayable_entry_groups(
    payload: Mapping[str, Any],
) -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    series = payload.get("series")
    if isinstance(series, Mapping):
        entries = [
            entry for entry in series.get("entries", []) if isinstance(entry, dict)
        ]
        if entries:
            groups.append(("series", entries))

    sections = payload.get("sections")
    if not isinstance(sections, list):
        return groups

    for section in sections:
        if not isinstance(section, Mapping):
            continue
        section_key = str(section.get("key") or "")
        if section_key in IGNORED_SECTION_KEYS:
            continue
        if section.get("visible_in_ui", True) is False:
            continue
        entries = [
            entry for entry in section.get("entries", []) if isinstance(entry, dict)
        ]
        if entries:
            groups.append((section_key, entries))
    return groups


def _displayable_entry_count(payload: Mapping[str, Any]) -> int:
    return sum(
        len(entries) for _section_key, entries in _displayable_entry_groups(payload)
    )


def _group_contains_seed(entries: list[dict], seed_media_id: str) -> bool:
    return any(_entry_media_id(entry) == seed_media_id for entry in entries)


def _canonical_has_richer_seed_context(
    *,
    seed_media_id: str,
    canonical_payload: Mapping[str, Any],
    scoped_payload: Mapping[str, Any],
) -> bool:
    canonical_count = _displayable_entry_count(canonical_payload)
    scoped_count = _displayable_entry_count(scoped_payload)
    if canonical_count <= scoped_count:
        return False

    for section_key, entries in _displayable_entry_groups(canonical_payload):
        if not _group_contains_seed(entries, seed_media_id):
            continue
        if section_key == "series" and len(entries) > 1:
            return True
        if section_key in RICH_LOCAL_SECTION_KEYS and len(entries) > 1:
            return True
        if len(entries) > 1 and any(_is_non_tv_entry(entry) for entry in entries):
            return True
    return False


def should_prefer_alias_global_payload(
    *,
    seed_media_id: str,
    canonical_payload: Mapping[str, Any] | None,
    scoped_payload: Mapping[str, Any] | None,
) -> bool:
    """Return whether alias/global UI context is richer than a scoped candidate."""
    seed_media_id = str(seed_media_id)
    if canonical_payload is None or scoped_payload is None:
        return False
    if not anime_franchise_cache.is_valid_global_payload(canonical_payload):
        return False
    if not anime_franchise_cache.is_valid_scoped_payload(scoped_payload):
        return False
    if not anime_franchise_cache.payload_covers_media_id(
        dict(canonical_payload), seed_media_id
    ):
        return False
    return _canonical_has_richer_seed_context(
        seed_media_id=seed_media_id,
        canonical_payload=canonical_payload,
        scoped_payload=scoped_payload,
    )
