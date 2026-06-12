"""Serialization and template-context helpers for MAL anime franchises."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from app import helpers
from app.anime_franchise_footer import enrich_franchise_entries_for_footer
from app.services.anime_franchise import AnimeFranchiseService


def _plain_value(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain_value(asdict(value))
    if isinstance(value, dict):
        return {key: _plain_value(inner_value) for key, inner_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(inner_value) for inner_value in value]
    return value


def _payload_get(franchise_payload, key, default=None):
    if isinstance(franchise_payload, dict):
        return franchise_payload.get(key, default)
    return getattr(franchise_payload, key, default)


def serialize_franchise_payload(franchise_payload, *, root_media_id=None) -> dict:
    """Convert a franchise UI payload to a cache-safe user-agnostic dict."""
    payload = {
        "root_media_id": str(
            root_media_id or _payload_get(franchise_payload, "root_media_id", "")
        ),
        "display_title": _payload_get(franchise_payload, "display_title", ""),
        "series": _payload_get(franchise_payload, "series", {}),
        "sections": _payload_get(franchise_payload, "sections", []),
        "canonical_root_media_id": str(
            _payload_get(franchise_payload, "canonical_root_media_id", "")
        ),
        "has_series_line": bool(
            _payload_get(franchise_payload, "has_series_line", False)
        ),
        "continuity_component_media_ids": _payload_get(
            franchise_payload, "continuity_component_media_ids", []
        ),
        "continuity_component_entries": _payload_get(
            franchise_payload, "continuity_component_entries", []
        ),
        "continuity_component_relations": _payload_get(
            franchise_payload, "continuity_component_relations", []
        ),
    }
    return _plain_value(payload)


def _copy_entries(entries):
    if not isinstance(entries, list):
        return []
    return [dict(entry) for entry in entries if isinstance(entry, dict)]


def _with_current_entry(entry: dict, current_media_id: str) -> dict:
    entry = dict(entry)
    entry["is_current"] = str(entry.get("media_id")) == current_media_id
    return entry


def has_displayable_franchise_entries(anime_franchise: dict | None) -> bool:
    """Return whether a prepared franchise context has entries to render."""
    if not isinstance(anime_franchise, dict):
        return False

    series = anime_franchise.get("series")
    series_entries = series.get("entries", []) if isinstance(series, dict) else []
    if series_entries:
        return True

    component_entries = _copy_entries(
        anime_franchise.get("continuity_component_entries", [])
    )
    if anime_franchise.get("has_series_line") is False and len(component_entries) > 1:
        return True

    sections = anime_franchise.get("sections", [])
    if not isinstance(sections, list):
        return False
    return any(
        isinstance(section, dict) and bool(section.get("entries"))
        for section in sections
    )


def _invert_continuity_relation(relation_type: str) -> str:
    if relation_type == "prequel":
        return "sequel"
    if relation_type == "sequel":
        return "prequel"
    return relation_type


def _relation_type_relative_to_current(
    *,
    current_media_id: str,
    target_media_id: str,
    relations: list[dict],
    ranks: dict[str, int],
) -> str | None:
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source_id = str(relation.get("source_media_id") or "")
        relation_target_id = str(relation.get("target_media_id") or "")
        relation_type = relation.get("relation_type")
        if relation_type not in {"prequel", "sequel"}:
            continue
        if source_id == current_media_id and relation_target_id == target_media_id:
            return str(relation_type)
        if source_id == target_media_id and relation_target_id == current_media_id:
            return _invert_continuity_relation(str(relation_type))

    current_rank = ranks.get(current_media_id)
    target_rank = ranks.get(target_media_id)
    if current_rank is None or target_rank is None:
        return None
    if target_rank < current_rank:
        return "prequel"
    if target_rank > current_rank:
        return "sequel"
    return None


def _build_no_series_render_continuity_entries(
    franchise_payload: dict,
    current_media_id: str,
) -> list[dict] | None:
    if franchise_payload.get("has_series_line") is not False:
        return None

    component_entries = franchise_payload.get("continuity_component_entries")
    component_relations = franchise_payload.get("continuity_component_relations")
    if not isinstance(component_entries, list) or not component_entries:
        return None
    if not isinstance(component_relations, list):
        return None

    continuity_section_entries: dict[str, dict] = {}
    for section in franchise_payload.get("sections", []):
        if not isinstance(section, dict) or section.get("key") != "continuity_extras":
            continue
        for entry in _copy_entries(section.get("entries", [])):
            media_id = str(entry.get("media_id") or "")
            if media_id:
                continuity_section_entries[media_id] = entry

    normalized_entries: list[dict] = []
    for index, component_entry in enumerate(_copy_entries(component_entries)):
        media_id = str(component_entry.get("media_id") or "")
        if not media_id or media_id == current_media_id:
            continue
        sort_rank = component_entry.get("section_sort_rank", index)
        try:
            normalized_rank = int(sort_rank)
        except (TypeError, ValueError):
            normalized_rank = index
        template_entry = continuity_section_entries.get(media_id, {})
        entry = {**component_entry, **template_entry}
        entry["media_id"] = media_id
        entry["section_sort_rank"] = normalized_rank
        normalized_entries.append(entry)

    ranks: dict[str, int] = {}
    for index, component_entry in enumerate(_copy_entries(component_entries)):
        media_id = str(component_entry.get("media_id") or "")
        if not media_id:
            continue
        sort_rank = component_entry.get("section_sort_rank", index)
        try:
            ranks[media_id] = int(sort_rank)
        except (TypeError, ValueError):
            ranks[media_id] = index

    normalized_entries.sort(
        key=lambda entry: (entry["section_sort_rank"], entry["media_id"])
    )
    for entry in normalized_entries:
        relation_type = _relation_type_relative_to_current(
            current_media_id=current_media_id,
            target_media_id=str(entry.get("media_id") or ""),
            relations=component_relations,
            ranks=ranks,
        )
        if relation_type is not None:
            entry["relation_type"] = relation_type

    return normalized_entries


def prepare_anime_franchise_context(
    request,
    franchise_payload: dict,
    media_metadata: dict,
):
    """Enrich a cached franchise payload with request-specific user data."""
    current_media_id = str(media_metadata.get("media_id") or "")
    series_payload = franchise_payload.get("series", {})
    prepared_series_entries = [
        _with_current_entry(
            {
                **entry,
                "series_label": entry.get("series_label") or f"Season {index}",
            },
            current_media_id,
        )
        for index, entry in enumerate(
            _copy_entries(series_payload.get("entries", [])),
            start=1,
        )
    ]
    no_series_continuity_entries = _build_no_series_render_continuity_entries(
        franchise_payload,
        current_media_id,
    )
    franchise_sections = []
    has_continuity_section = False
    continuity_section_title = "Main Story Extras"
    for section in franchise_payload.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_key = section.get("key")
        section_title = section.get("title")
        if not section_key or not section_title:
            continue
        if section_key == "continuity_extras":
            has_continuity_section = True
            continuity_section_title = section_title
        section_entries = _copy_entries(section.get("entries", []))
        if (
            section_key == "continuity_extras"
            and no_series_continuity_entries is not None
        ):
            section_entries = no_series_continuity_entries
        franchise_sections.append(
            {
                "key": section_key,
                "title": section_title,
                "entries": helpers.enrich_items_with_user_data(
                    request,
                    enrich_franchise_entries_for_footer(
                        [
                            _with_current_entry(entry, current_media_id)
                            for entry in section_entries
                        ],
                        media_metadata,
                    ),
                    section_key,
                ),
                "visible_in_ui": section.get("visible_in_ui", True),
                "hidden_if_empty": section.get("hidden_if_empty", True),
            }
        )

    if (
        not has_continuity_section
        and no_series_continuity_entries is not None
        and no_series_continuity_entries
    ):
        franchise_sections.append(
            {
                "key": "continuity_extras",
                "title": continuity_section_title,
                "entries": helpers.enrich_items_with_user_data(
                    request,
                    enrich_franchise_entries_for_footer(
                        [
                            _with_current_entry(entry, current_media_id)
                            for entry in no_series_continuity_entries
                        ],
                        media_metadata,
                    ),
                    "continuity_extras",
                ),
                "visible_in_ui": True,
                "hidden_if_empty": True,
            }
        )

    return {
        "root_media_id": franchise_payload.get("root_media_id", ""),
        "display_title": franchise_payload.get("display_title", ""),
        "series": {
            "key": AnimeFranchiseService.SERIES_LINE_KEY,
            "title": series_payload.get("title", "Series"),
            "entries": helpers.enrich_items_with_user_data(
                request,
                prepared_series_entries,
                AnimeFranchiseService.SERIES_LINE_KEY,
            ),
        },
        "sections": franchise_sections,
        "truncated": franchise_payload.get("truncated", False),
    }
