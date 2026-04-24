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


class ViewModelAdapter:
    """Convert compiled blocks/sections into an integration-friendly dict payload."""

    def adapt(
        self,
        *,
        root_media_id: str,
        display_title: str,
        series_block: SeriesBlock,
        sections: list[CompiledSection],
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
                        "is_light": False,
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
                ]
            },
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
                            "media_type": candidate.route_media_type,
                            "anime_media_type": candidate.media_type,
                            "is_light": candidate.is_light,
                            "relation_type": candidate.relation_type,
                            "start_date": candidate.start_date,
                            "runtime_minutes": candidate.runtime_minutes,
                            "episode_count": candidate.episode_count,
                            "linked_series_line_media_id": candidate.linked_series_line_media_id,
                            "linked_series_line_index": candidate.linked_series_line_index,
                            "is_current": candidate.is_current,
                            "badges": list(candidate.badges),
                        }
                        for candidate in section.entries
                    ],
                }
                for section in sections
            ],
        )
