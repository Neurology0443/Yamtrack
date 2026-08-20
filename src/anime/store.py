from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from anime.metadata import (
    AnimeMetadataSnapshot,
    AnimeMetadataUnavailable,
    AnimeRecommendation,
    AnimeRelation,
)
from anime.models import AnimeMetadataRecord
from app.providers import services

MAL_METADATA_FIELDS = (
    "title,alternative_titles,main_picture,media_type,start_date,end_date,"
    "synopsis,status,genres,mean,num_scoring_users,num_episodes,"
    "average_episode_duration,studios,start_season,broadcast,source,"
    "related_anime,recommendations"
)
REFRESH_INTERVAL = timedelta(hours=24)
ERROR_COOLDOWN = timedelta(hours=1)
MAX_ERROR_MESSAGE_LENGTH = 2000


class MalAnimeMetadataStore:
    """The sole MAL metadata boundary for the Anime subsystem."""

    source = "mal"

    def get_record(self, media_id: int) -> AnimeMetadataRecord | None:
        """Return local persistence state, including failed-first-fetch state."""
        return AnimeMetadataRecord.objects.filter(
            source=self.source,
            media_id=media_id,
        ).first()

    def get_local(self, media_id: int) -> AnimeMetadataSnapshot | None:
        """Return valid persisted metadata without network access."""
        record = self.get_record(media_id)
        if record is None or record.fetched_at is None:
            return None
        return self.to_snapshot(record)

    def refresh_is_due(self, record: AnimeMetadataRecord, *, now: Any) -> bool:
        """Return whether a valid record should be refreshed."""
        return record.refresh_after is None or record.refresh_after <= now

    def error_cooldown_active(
        self,
        record: AnimeMetadataRecord,
        *,
        now: Any,
    ) -> bool:
        """Return whether a recent provider failure suppresses another attempt."""
        return bool(
            record.last_refresh_error_at
            and record.last_refresh_error_at > now - ERROR_COOLDOWN
        )

    def refresh(self, media_id: int) -> AnimeMetadataSnapshot:
        """Fetch and normalize outside a transaction, then atomically persist."""
        try:
            payload = self._fetch_provider_payload(media_id)
            normalized = self._normalize(media_id, payload)
        except Exception as exc:
            self._record_refresh_failure(media_id, exc)
            raise AnimeMetadataUnavailable(media_id) from exc

        now = timezone.now()
        with transaction.atomic():
            record, _ = AnimeMetadataRecord.objects.update_or_create(
                source=self.source,
                media_id=media_id,
                defaults={
                    **normalized,
                    "fetched_at": now,
                    "refresh_after": now + REFRESH_INTERVAL,
                    "last_refresh_attempt_at": now,
                    "last_refresh_error_at": None,
                    "last_error_message": None,
                },
            )
        return self.to_snapshot(record)

    def _fetch_provider_payload(self, media_id: int) -> dict[str, Any]:
        return services.api_request(
            "mal",
            "GET",
            f"https://api.myanimelist.net/v2/anime/{media_id}",
            params={"fields": MAL_METADATA_FIELDS},
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )

    def _normalize(self, media_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self._positive_int(media_id)
        if not isinstance(payload, dict):
            msg = "MAL metadata response must be an object"
            raise TypeError(msg)
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            msg = "MAL metadata response has no valid title"
            raise ValueError(msg)

        relations = [
            {
                "media_id": self._positive_int(item.get("node", {}).get("id")),
                "relation_type": self._required_string(item.get("relation_type")),
            }
            for item in self._list(payload.get("related_anime"))
        ]
        recommendations = [
            {
                "media_id": self._positive_int(item.get("node", {}).get("id")),
                "count": self._nonnegative_int(item.get("num_recommendations")),
            }
            for item in self._list(payload.get("recommendations"))
        ]
        picture = self._mapping(payload.get("main_picture"))
        season = self._mapping(payload.get("start_season"))
        broadcast = self._mapping(payload.get("broadcast"))
        synopsis = payload.get("synopsis")
        episodes = payload.get("num_episodes")
        runtime = payload.get("average_episode_duration")
        return {
            "canonical_title": title,
            "alternative_title_en": self._mapping(
                payload.get("alternative_titles"),
            ).get("en")
            or None,
            "image": picture.get("large") or picture.get("medium") or None,
            "synopsis": synopsis if isinstance(synopsis, str) and synopsis else None,
            "genres": [
                self._required_string(item.get("name"))
                for item in self._list(payload.get("genres"))
            ],
            "score": self._optional_float(payload.get("mean")),
            "score_count": self._optional_nonnegative_int(
                payload.get("num_scoring_users"),
            ),
            "episode_count": self._optional_positive_int(episodes),
            "media_type": self._optional_string(payload.get("media_type")),
            "start_date": self._optional_string(payload.get("start_date")),
            "end_date": self._optional_string(payload.get("end_date")),
            "status": self._optional_string(payload.get("status")),
            "runtime": self._optional_positive_int(runtime),
            "studios": [
                self._required_string(item.get("name"))
                for item in self._list(payload.get("studios"))
            ],
            "season_year": self._optional_positive_int(season.get("year")),
            "season_name": self._optional_string(season.get("season")),
            "broadcast_day": self._optional_string(broadcast.get("day_of_the_week")),
            "broadcast_time": self._optional_string(broadcast.get("start_time")),
            "source_material": self._optional_string(payload.get("source")),
            "relations": relations,
            "recommendations": recommendations,
        }

    def _record_refresh_failure(self, media_id: int, error: Exception) -> None:
        now = timezone.now()
        message = f"{type(error).__name__}: {error}"[:MAX_ERROR_MESSAGE_LENGTH]
        AnimeMetadataRecord.objects.update_or_create(
            source=self.source,
            media_id=media_id,
            defaults={
                "last_refresh_attempt_at": now,
                "last_refresh_error_at": now,
                "last_error_message": message,
            },
        )

    def to_snapshot(self, record: AnimeMetadataRecord) -> AnimeMetadataSnapshot:
        """Convert persistence to the only metadata object exposed to consumers."""
        if record.fetched_at is None or not record.canonical_title:
            msg = "A valid persisted fetch is required to create a snapshot"
            raise ValueError(msg)
        if record.refresh_after is None:
            msg = "Valid persisted metadata must have refresh_after"
            raise ValueError(msg)
        return AnimeMetadataSnapshot(
            media_id=record.media_id,
            source=record.source,
            canonical_title=record.canonical_title,
            alternative_title_en=record.alternative_title_en,
            image=record.image,
            synopsis=record.synopsis,
            genres=tuple(record.genres),
            score=record.score,
            score_count=record.score_count,
            episode_count=record.episode_count,
            media_type=record.media_type,
            start_date=record.start_date,
            end_date=record.end_date,
            status=record.status,
            runtime=record.runtime,
            studios=tuple(record.studios),
            season_year=record.season_year,
            season_name=record.season_name,
            broadcast_day=record.broadcast_day,
            broadcast_time=record.broadcast_time,
            source_material=record.source_material,
            relations=tuple(AnimeRelation(**item) for item in record.relations),
            recommendations=tuple(
                AnimeRecommendation(**item) for item in record.recommendations
            ),
            fetched_at=record.fetched_at,
            refresh_after=record.refresh_after,
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError
        return value

    @staticmethod
    def _list(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        valid_items = isinstance(value, list) and all(
            isinstance(item, dict) for item in value
        )
        if not valid_items:
            raise TypeError
        return value

    @staticmethod
    def _required_string(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError
        return value

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError
        return value

    @staticmethod
    def _positive_int(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError
        return value

    @classmethod
    def _optional_positive_int(cls, value: Any) -> int | None:
        if value in (None, 0):
            return None
        return cls._positive_int(value)

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError
        return value

    @classmethod
    def _optional_nonnegative_int(cls, value: Any) -> int | None:
        if value is None:
            return None
        return cls._nonnegative_int(value)

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError
        return float(value)
