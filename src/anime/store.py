# ruff: noqa: EM101, EM102, TRY003

import logging
from datetime import datetime, timedelta
from typing import Any

import requests
from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from anime.metadata import (
    AnimeMetadataSnapshot,
    AnimeMetadataUnavailable,
    AnimeRecommendation,
    AnimeRelation,
    InvalidAnimeMetadataPayload,
    validate_media_id,
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
ENQUEUE_THROTTLE = timedelta(minutes=5)
MAX_ERROR_MESSAGE_LENGTH = 2000
EXPECTED_PROVIDER_EXCEPTIONS = (
    requests.exceptions.RequestException,
    services.ProviderAPIError,
)
logger = logging.getLogger(__name__)


class MalAnimeMetadataStore:
    """The sole MAL metadata boundary for the Anime subsystem."""

    source = "mal"

    def get_record(self, media_id: int) -> AnimeMetadataRecord | None:
        """Return local persistence state, including failed-first-fetch state."""
        validate_media_id(media_id)
        return AnimeMetadataRecord.objects.filter(
            source=self.source,
            media_id=media_id,
        ).first()

    def get_local(self, media_id: int) -> AnimeMetadataSnapshot | None:
        """Return valid persisted metadata without network access."""
        validate_media_id(media_id)
        record = self.get_record(media_id)
        if record is None or record.fetched_at is None:
            return None
        return self.to_snapshot(record)

    def refresh_is_due(self, record: AnimeMetadataRecord, *, now: datetime) -> bool:
        """Return whether a valid record should be refreshed."""
        if record.fetched_at is None:
            return True
        if record.refresh_after is None:
            msg = "Valid metadata requires refresh_after"
            raise ValueError(msg)
        return record.refresh_after <= now

    def error_cooldown_active(
        self,
        record: AnimeMetadataRecord,
        *,
        now: datetime,
    ) -> bool:
        """Return whether a recent provider failure suppresses another attempt."""
        return bool(
            record.last_refresh_error_at
            and record.last_refresh_error_at > now - ERROR_COOLDOWN
        )

    def refresh(self, media_id: int) -> AnimeMetadataSnapshot:
        """Fetch and normalize outside a transaction, then atomically persist."""
        validate_media_id(media_id)
        try:
            payload = self._fetch_provider_payload(media_id)
        except EXPECTED_PROVIDER_EXCEPTIONS as exc:
            self._record_refresh_failure(media_id, exc)
            raise AnimeMetadataUnavailable(media_id) from exc
        try:
            normalized = self._normalize(media_id, payload)
        except InvalidAnimeMetadataPayload as exc:
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

    def claim_async_refresh(
        self,
        record: AnimeMetadataRecord,
        *,
        now: datetime,
    ) -> bool:
        """Atomically claim one stale refresh without relying on the queue."""
        validate_media_id(record.media_id)
        cutoff = now - ENQUEUE_THROTTLE
        try:
            claimed = (
                AnimeMetadataRecord.objects.filter(
                    pk=record.pk,
                    refresh_after__lte=now,
                )
                .filter(
                    Q(last_refresh_attempt_at__isnull=True)
                    | Q(last_refresh_attempt_at__lte=cutoff),
                )
                .filter(
                    Q(last_refresh_error_at__isnull=True)
                    | Q(last_refresh_error_at__lte=now - ERROR_COOLDOWN),
                )
                .update(last_refresh_attempt_at=now)
            )
        except OperationalError:
            logger.exception(
                "Could not claim MAL metadata refresh for anime %s",
                record.media_id,
            )
            return False
        return bool(claimed)

    def _fetch_provider_payload(self, media_id: int) -> dict[str, Any]:
        return services.api_request(
            "mal",
            "GET",
            f"https://api.myanimelist.net/v2/anime/{media_id}",
            params={"fields": MAL_METADATA_FIELDS},
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )

    def _normalize(self, media_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        validate_media_id(media_id)
        if not isinstance(payload, dict):
            raise InvalidAnimeMetadataPayload("MAL metadata response must be an object")
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise InvalidAnimeMetadataPayload(
                "MAL metadata response has no valid title"
            )

        relations = []
        for index, item in enumerate(
            self._list(payload.get("related_anime"), field="related_anime")
        ):
            node = self._mapping(
                item.get("node"),
                field=f"related_anime[{index}].node",
                optional=False,
            )
            relations.append(
                {
                    "media_id": self._positive_int(
                        node.get("id"),
                        field=f"related_anime[{index}].node.id",
                    ),
                    "relation_type": self._required_string(
                        item.get("relation_type"),
                        field=f"related_anime[{index}].relation_type",
                    ),
                }
            )
        recommendations = []
        for index, item in enumerate(
            self._list(payload.get("recommendations"), field="recommendations")
        ):
            node = self._mapping(
                item.get("node"),
                field=f"recommendations[{index}].node",
                optional=False,
            )
            recommendations.append(
                {
                    "media_id": self._positive_int(
                        node.get("id"),
                        field=f"recommendations[{index}].node.id",
                    ),
                    "count": self._nonnegative_int(
                        item.get("num_recommendations"),
                        field=f"recommendations[{index}].num_recommendations",
                    ),
                }
            )
        picture = self._mapping(payload.get("main_picture"), field="main_picture")
        season = self._mapping(payload.get("start_season"), field="start_season")
        broadcast = self._mapping(payload.get("broadcast"), field="broadcast")
        return {
            "canonical_title": title,
            "alternative_title_en": self._optional_string(
                self._mapping(
                    payload.get("alternative_titles"),
                    field="alternative_titles",
                ).get("en"),
                field="alternative_titles.en",
            ),
            "image": self._optional_string(
                picture.get("large") or picture.get("medium"), field="main_picture"
            ),
            "synopsis": self._optional_string(
                payload.get("synopsis"), field="synopsis"
            ),
            "genres": [
                self._required_string(item.get("name"), field=f"genres[{index}].name")
                for index, item in enumerate(
                    self._list(payload.get("genres"), field="genres")
                )
            ],
            "score": self._optional_float(payload.get("mean"), field="mean"),
            "score_count": self._optional_nonnegative_int(
                payload.get("num_scoring_users"), field="num_scoring_users"
            ),
            "episode_count": self._optional_positive_int(
                payload.get("num_episodes"), field="num_episodes"
            ),
            "media_type": self._optional_string(
                payload.get("media_type"), field="media_type"
            ),
            "start_date": self._optional_string(
                payload.get("start_date"), field="start_date"
            ),
            "end_date": self._optional_string(
                payload.get("end_date"), field="end_date"
            ),
            "status": self._optional_string(payload.get("status"), field="status"),
            "runtime": self._optional_positive_int(
                payload.get("average_episode_duration"),
                field="average_episode_duration",
            ),
            "studios": [
                self._required_string(item.get("name"), field=f"studios[{index}].name")
                for index, item in enumerate(
                    self._list(payload.get("studios"), field="studios")
                )
            ],
            "season_year": self._optional_positive_int(
                season.get("year"), field="start_season.year"
            ),
            "season_name": self._optional_string(
                season.get("season"), field="start_season.season"
            ),
            "broadcast_day": self._optional_string(
                broadcast.get("day_of_the_week"), field="broadcast.day_of_the_week"
            ),
            "broadcast_time": self._optional_string(
                broadcast.get("start_time"), field="broadcast.start_time"
            ),
            "source_material": self._optional_string(
                payload.get("source"), field="source"
            ),
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
    def _mapping(
        value: Any,
        *,
        field: str,
        optional: bool = True,
    ) -> dict[str, Any]:
        if value is None:
            if optional:
                return {}
            raise InvalidAnimeMetadataPayload(f"{field} must be an object")
        if not isinstance(value, dict):
            raise InvalidAnimeMetadataPayload(f"{field} must be an object")
        return value

    @staticmethod
    def _list(value: Any, *, field: str) -> list[dict[str, Any]]:
        if value is None:
            return []
        valid_items = isinstance(value, list) and all(
            isinstance(item, dict) for item in value
        )
        if not valid_items:
            raise InvalidAnimeMetadataPayload(f"{field} must be a list of objects")
        return value

    @staticmethod
    def _required_string(value: Any, *, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise InvalidAnimeMetadataPayload(f"{field} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(value: Any, *, field: str) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise InvalidAnimeMetadataPayload(f"{field} must be a string or null")
        return value

    @staticmethod
    def _positive_int(value: Any, *, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise InvalidAnimeMetadataPayload(f"{field} must be a positive integer")
        return value

    @classmethod
    def _optional_positive_int(cls, value: Any, *, field: str) -> int | None:
        if value in (None, 0):
            return None
        return cls._positive_int(value, field=field)

    @staticmethod
    def _nonnegative_int(value: Any, *, field: str) -> int:
        if type(value) is not int or value < 0:
            raise InvalidAnimeMetadataPayload(f"{field} must be a non-negative integer")
        return value

    @classmethod
    def _optional_nonnegative_int(cls, value: Any, *, field: str) -> int | None:
        if value is None:
            return None
        return cls._nonnegative_int(value, field=field)

    @staticmethod
    def _optional_float(value: Any, *, field: str) -> float | None:
        if value is None:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InvalidAnimeMetadataPayload(f"{field} must be numeric or null")
        return float(value)
