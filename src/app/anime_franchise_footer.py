from app.providers import mal

FORMAT_LABEL_MAP = {
    "tv": "TV",
    "ova": "OVA",
    "ona": "ONA",
    "tv_special": "TV Special",
    "cm": "CM",
    "pv": "PV",
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


def enrich_franchise_entries_for_footer(
    entries: list[dict],
    media_metadata: dict,
) -> list[dict]:
    """Attach page-local footer presentation fields to franchise entries."""
    direct_relation_map = _build_page_local_relation_map(media_metadata)
    return [
        {
            **entry,
            "footer_format": _format_footer_format_label(
                entry.get("anime_media_type"),
            ),
            "footer_format_value": entry.get("anime_media_type"),
            "footer_relation_type": direct_relation_map.get(str(entry.get("media_id"))),
            "footer_relation_active": bool(
                direct_relation_map.get(str(entry.get("media_id"))),
            ),
        }
        for entry in entries
    ]
