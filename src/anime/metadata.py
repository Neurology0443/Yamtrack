from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AnimeRelation:
    """A normalized MAL anime relation."""

    media_id: int
    relation_type: str


@dataclass(frozen=True, slots=True)
class AnimeRecommendation:
    """A normalized MAL recommendation."""

    media_id: int
    count: int


@dataclass(frozen=True, slots=True)
class AnimeMetadataSnapshot:
    """Immutable, provider-independent view of persisted anime metadata."""

    media_id: int
    source: str
    canonical_title: str
    alternative_title_en: str | None
    image: str | None
    synopsis: str | None
    genres: tuple[str, ...]
    score: float | None
    score_count: int | None
    episode_count: int | None
    media_type: str | None
    start_date: str | None
    end_date: str | None
    status: str | None
    runtime: int | None
    studios: tuple[str, ...]
    season_year: int | None
    season_name: str | None
    broadcast_day: str | None
    broadcast_time: str | None
    source_material: str | None
    relations: tuple[AnimeRelation, ...]
    recommendations: tuple[AnimeRecommendation, ...]
    fetched_at: datetime
    refresh_after: datetime


class AnimeMetadataUnavailable(Exception):  # noqa: N818
    """Raised when no valid local or provider metadata is available."""

    def __init__(self, media_id: int) -> None:
        """Build an error identifying the unavailable MAL anime."""
        super().__init__(f"Anime metadata is unavailable for MAL anime {media_id}")
