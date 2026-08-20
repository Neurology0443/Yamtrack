import logging
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from anime.metadata import AnimeMetadataSnapshot, AnimeMetadataUnavailable
from anime.models import AnimeMetadataRecord
from anime.store import ERROR_COOLDOWN, MalAnimeMetadataStore

ENQUEUE_THROTTLE = timedelta(minutes=5)
logger = logging.getLogger(__name__)


class GetAnimeMetadata:
    """Serve local metadata first and orchestrate required background work."""

    def __init__(self, store: MalAnimeMetadataStore | None = None) -> None:
        """Allow dependency injection while supplying the production MAL store."""
        self.store = store or MalAnimeMetadataStore()

    def execute(self, media_id: int) -> AnimeMetadataSnapshot:
        """Return metadata, synchronously fetching only without a valid local copy."""
        record = self.store.get_record(media_id)
        now = timezone.now()
        if record is None or record.fetched_at is None:
            if record is not None and self.store.error_cooldown_active(record, now=now):
                raise AnimeMetadataUnavailable(media_id)
            return self.store.refresh(media_id)

        snapshot = self.store.to_snapshot(record)
        if self.store.refresh_is_due(record, now=now):
            self._schedule_refresh_if_allowed(record, now=now)
        return snapshot

    def _schedule_refresh_if_allowed(
        self,
        record: AnimeMetadataRecord,
        *,
        now: datetime,
    ) -> None:
        cutoff = now - ENQUEUE_THROTTLE
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
        if claimed:
            from anime.tasks import refresh_anime_metadata  # noqa: PLC0415

            try:
                refresh_anime_metadata.delay(record.media_id)
            except Exception:  # Celery is optional to the local-first read path.
                logger.exception(
                    "Could not enqueue MAL metadata refresh for anime %s",
                    record.media_id,
                )


class RefreshAnimeMetadata:
    """Application entry point for an explicitly requested provider refresh."""

    def __init__(self, store: MalAnimeMetadataStore | None = None) -> None:
        """Allow dependency injection while supplying the production MAL store."""
        self.store = store or MalAnimeMetadataStore()

    def execute(self, media_id: int) -> AnimeMetadataSnapshot:
        """Refresh MAL metadata through the store."""
        return self.store.refresh(media_id)
