"""Adapter from pipeline objects to a template-oriented payload."""

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
    """Convert compiled model into an integration-friendly dict structure."""

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
                        "media_type": entry.media_type,
                        "start_date": entry.start_date,
                        "runtime_minutes": entry.runtime_minutes,
                        "episode_count": entry.episode_count,
                        "index": entry.index,
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
                    "entries": [
                        {
                            "media_id": candidate.media_id,
                            "title": candidate.title,
                            "image": candidate.image,
                            "source": candidate.source,
                            "media_type": candidate.media_type,
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
