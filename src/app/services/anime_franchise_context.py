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
    serialized_root_media_id = str(
        root_media_id or _payload_get(franchise_payload, "root_media_id", "")
    )
    canonical_root_media_id = _payload_get(
        franchise_payload,
        "canonical_root_media_id",
        "",
    )
    if not canonical_root_media_id:
        canonical_root_media_id = serialized_root_media_id

    payload = {
        "root_media_id": serialized_root_media_id,
        "canonical_root_media_id": str(canonical_root_media_id),
        "display_title": _payload_get(franchise_payload, "display_title", ""),
        "series": _payload_get(franchise_payload, "series", {}),
        "sections": _payload_get(franchise_payload, "sections", []),
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

    sections = anime_franchise.get("sections", [])
    if not isinstance(sections, list):
        return False
    return any(
        isinstance(section, dict) and bool(section.get("entries"))
        for section in sections
    )


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
    copied_sections = []
    all_footer_entries = [*prepared_series_entries]
    for section in franchise_payload.get("sections", []):
        if not isinstance(section, dict):
            continue
        copied_entries = [
            _with_current_entry(entry, current_media_id)
            for entry in _copy_entries(section.get("entries", []))
        ]
        copied_sections.append((section, copied_entries))
        all_footer_entries.extend(copied_entries)

    franchise_sections = []
    for section, section_entries in copied_sections:
        if not isinstance(section, dict):
            continue
        section_key = section.get("key")
        section_title = section.get("title")
        if not section_key or not section_title:
            continue
        franchise_sections.append(
            {
                "key": section_key,
                "title": section_title,
                "entries": helpers.enrich_items_with_user_data(
                    request,
                    enrich_franchise_entries_for_footer(
                        section_entries,
                        media_metadata,
                        series_entries=prepared_series_entries,
                        all_entries=all_footer_entries,
                    ),
                    section_key,
                ),
                "visible_in_ui": section.get("visible_in_ui", True),
                "hidden_if_empty": section.get("hidden_if_empty", True),
            }
        )

    return {
        "root_media_id": franchise_payload.get("root_media_id", ""),
        "canonical_root_media_id": franchise_payload.get(
            "canonical_root_media_id",
            franchise_payload.get("root_media_id", ""),
        ),
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
