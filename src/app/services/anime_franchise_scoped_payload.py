"""Build scoped direct MAL anime franchise payloads for non-canonical seeds."""

from __future__ import annotations

from django.conf import settings

DISPLAYABLE_LOCAL_RELATIONS = {"full_story", "sequel", "prequel"}


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
        "media_type": target_node.media_type,
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


def build_scoped_seed_payload_from_snapshot(
    snapshot,
    *,
    seed_media_id: str,
) -> dict | None:
    """Return a direct scoped payload for a non-TV seed using snapshot data only."""
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
