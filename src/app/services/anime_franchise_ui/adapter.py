"""Adapt compiled pipeline output to a template-oriented payload shape.

The adapter is a compatibility layer only: no placement or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rule_types import CompiledSection
from .series import SeriesBlock


@dataclass(frozen=True)
class AnimeFranchiseUiPayload:
    """UI payload with fixed series block and dynamic secondary sections."""

    root_media_id: str
    display_title: str
    series: dict
    sections: list[dict]
    canonical_root_media_id: str
    has_series_line: bool
    continuity_component_media_ids: list[str]
    continuity_component_entries: list[dict]
    continuity_component_relations: list[dict]


class ViewModelAdapter:
    """Convert compiled blocks/sections into an integration-friendly dict payload."""

    def adapt(
        self,
        *,
        root_media_id: str,
        display_title: str,
        series_block: SeriesBlock,
        sections: list[CompiledSection],
        canonical_root_media_id: str = "",
        has_series_line: bool = False,
        continuity_component_media_ids: list[str] | None = None,
        continuity_component_entries: list[dict] | None = None,
        continuity_component_relations: list[dict] | None = None,
    ) -> AnimeFranchiseUiPayload:
        return AnimeFranchiseUiPayload(
            root_media_id=root_media_id,
            display_title=display_title,
            series={
                "key": series_block.key,
                "title": series_block.title,
                "entries": [
                    {
                        "media_id": entry.media_id,
                        "title": entry.title,
                        "image": entry.image,
                        "source": entry.source,
                        "media_type": "anime",
                        "anime_media_type": entry.media_type,
                        "start_date": entry.start_date,
                        "runtime_minutes": entry.runtime_minutes,
                        "episode_count": entry.episode_count,
                        "index": entry.index,
                        "relation_type": None,
                        "linked_series_line_media_id": None,
                        "linked_series_line_index": None,
                        "is_current": entry.is_current,
                    }
                    for entry in series_block.entries
                ],
            },
            canonical_root_media_id=str(canonical_root_media_id),
            has_series_line=bool(has_series_line),
            continuity_component_media_ids=[
                str(media_id) for media_id in (continuity_component_media_ids or [])
            ],
            continuity_component_entries=[
                dict(entry)
                for entry in (continuity_component_entries or [])
                if isinstance(entry, dict)
            ],
            continuity_component_relations=[
                dict(relation)
                for relation in (continuity_component_relations or [])
                if isinstance(relation, dict)
            ],
            sections=[
                {
                    "key": section.key,
                    "title": section.title,
                    "order": section.order,
                    "hidden_if_empty": section.hidden_if_empty,
                    "visible_in_ui": bool(section.metadata.get("visible_in_ui", True)),
                    "entries": [
                        {
                            "media_id": candidate.media_id,
                            "title": candidate.title,
                            "image": candidate.image,
                            "source": candidate.source,
                            "media_type": "anime",
                            "anime_media_type": candidate.media_type,
                            "relation_type": candidate.relation_type,
                            "start_date": candidate.start_date,
                            "runtime_minutes": candidate.runtime_minutes,
                            "episode_count": candidate.episode_count,
                            "linked_series_line_media_id": (
                                candidate.linked_series_line_media_id
                            ),
                            "linked_series_line_index": (
                                candidate.linked_series_line_index
                            ),
                            "is_current": candidate.is_current,
                            "badges": list(candidate.badges),
                        }
                        for candidate in section.entries
                    ],
                }
                for section in sections
            ],
        )
