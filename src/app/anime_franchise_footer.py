from app.providers import mal

FORMAT_LABEL_MAP = {
    "tv": "TV",
    "ova": "OVA",
    "ona": "ONA",
    "tv_special": "TV Special",
    "cm": "CM",
    "pv": "PV",
}

RELATION_TOOLTIP_PREFIX_MAP = {
    "prequel": "Prequel to",
    "sequel": "Sequel to",
    "summary": "Summary of",
    "full_story": "Full story of",
    "side_story": "Side story from",
    "alternative_setting": "Alternative setting from",
    "alternative_version": "Alternative version from",
    "spin_off": "Spin-off from",
    "parent_story": "Parent story of",
    "character": "Character relation from",
}


def _format_footer_format_label(anime_media_type: str | None) -> str | None:
    """Convert MAL anime format to footer-friendly display text."""
    if not anime_media_type:
        return None
    return FORMAT_LABEL_MAP.get(
        anime_media_type,
        anime_media_type.replace("_", " ").title(),
    )


def _build_page_local_relation_map(media_metadata: dict) -> dict[str, str]:
    """Map related media IDs to direct normalized relation_type for current page."""
    related = media_metadata.get("related") or {}
    direct_relations = related.get("related_anime") or []
    relation_map = {}
    for related_item in direct_relations:
        related_media_id = related_item.get("media_id")
        if related_media_id is None:
            continue
        relation_type = mal.normalize_relation_type(
            related_item.get("relation_type"),
        )
        if relation_type:
            relation_map[str(related_media_id)] = relation_type
    return relation_map


def _format_footer_relation_label(relation_type: str | None) -> str | None:
    """Convert normalized relation_type to footer-friendly display text."""
    if not relation_type:
        return None
    return relation_type.replace("_", " ").title()


def _build_footer_relation_tooltip(
    relation_type: str | None,
    source_title: str | None,
) -> str:
    """Build a mono-relation tooltip for the displayed footer relation."""
    if not relation_type:
        return ""
    if not source_title:
        return ""
    prefix = RELATION_TOOLTIP_PREFIX_MAP.get(relation_type)
    if not prefix:
        return ""
    return f"{prefix}: {source_title}"


def _build_series_title_map(series_entries: list[dict] | None) -> dict[str, str]:
    """Map series-line media IDs to their display-friendly title."""
    title_map = {}
    if not series_entries:
        return title_map
    for entry in series_entries:
        if not isinstance(entry, dict):
            continue
        media_id = entry.get("media_id")
        if media_id is None:
            continue
        title = entry.get("series_label") or entry.get("title")
        if not title:
            continue
        title_map[str(media_id)] = title
    return title_map


def _resolve_footer_relation_source_title(
    entry: dict,
    series_titles_by_media_id: dict[str, str],
) -> str | None:
    """Resolve the displayed footer relation source from series-line entries."""
    media_id = entry.get("linked_series_line_media_id")
    if media_id is None:
        return None
    return series_titles_by_media_id.get(str(media_id))


def _resolve_current_page_title(media_metadata: dict) -> str | None:
    """Resolve the current page title for active page-local relations."""
    return (
        media_metadata.get("season_title")
        or media_metadata.get("title")
        or media_metadata.get("name")
    )


def enrich_franchise_entries_for_footer(
    entries: list[dict],
    media_metadata: dict,
    *,
    series_entries: list[dict] | None = None,
) -> list[dict]:
    """Attach page-local footer presentation fields to franchise entries."""
    direct_relation_map = _build_page_local_relation_map(media_metadata)
    current_page_title = _resolve_current_page_title(media_metadata)
    series_titles_by_media_id = _build_series_title_map(series_entries)
    enriched_entries = []
    for entry in entries:
        media_id = entry.get("media_id")
        direct_relation_value = direct_relation_map.get(str(media_id))
        footer_relation_value = direct_relation_value or mal.normalize_relation_type(
            entry.get("relation_type"),
        )
        if direct_relation_value:
            source_title = current_page_title
        else:
            source_title = _resolve_footer_relation_source_title(
                entry,
                series_titles_by_media_id,
            )
        enriched_entries.append(
            {
                **entry,
                "footer_format": _format_footer_format_label(
                    entry.get("anime_media_type"),
                ),
                "footer_format_value": entry.get("anime_media_type"),
                "footer_relation_value": footer_relation_value,
                "footer_relation_label": _format_footer_relation_label(
                    footer_relation_value,
                ),
                "footer_relation_active": bool(direct_relation_value),
                "footer_relation_tooltip": _build_footer_relation_tooltip(
                    footer_relation_value,
                    source_title,
                ),
            }
        )
    return enriched_entries
