"""Builder for fixed and immutable `Series` UI block."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


@dataclass(frozen=True)
class SeriesEntry:
    """One fixed entry in the Series line."""

    media_id: str
    title: str
    image: str
    source: str
    media_type: str
    start_date: date | None
    runtime_minutes: int | None
    episode_count: int | None
    index: int
    is_current: bool


@dataclass(frozen=True)
class SeriesBlock:
    """Immutable top-level Series block."""

    key: str
    title: str
    entries: tuple[SeriesEntry, ...]


class SeriesBuilder:
    """Build the dedicated Series block from snapshot.series_line only."""

    def build(self, snapshot: AnimeFranchiseSnapshot) -> SeriesBlock:
        entries = tuple(
            SeriesEntry(
                media_id=node.media_id,
                title=node.title,
                image=node.image,
                source=node.source,
                media_type=node.media_type,
                start_date=node.start_date,
                runtime_minutes=node.runtime_minutes,
                episode_count=node.episode_count,
                index=index,
                is_current=node.media_id == snapshot.root_node.media_id,
            )
            for index, node in enumerate(snapshot.series_line)
        )
        return SeriesBlock(
            key="series",
            title="Series",
            entries=entries,
        )
