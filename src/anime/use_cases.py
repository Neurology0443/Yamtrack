from django.utils import timezone

from anime.enqueue import enqueue_anime_metadata_refresh
from anime.metadata import (
    AnimeMetadataSnapshot,
    AnimeMetadataUnavailable,
    validate_media_id,
)
from anime.store import MalAnimeMetadataStore


class GetAnimeMetadata:
    """Serve local metadata first and orchestrate required background work."""

    def __init__(
        self,
        store: MalAnimeMetadataStore | None = None,
        enqueue_refresh=None,
    ) -> None:
        """Allow dependency injection while supplying the production MAL store."""
        self.store = store or MalAnimeMetadataStore()
        self.enqueue_refresh = enqueue_refresh or enqueue_anime_metadata_refresh

    def execute(self, media_id: int) -> AnimeMetadataSnapshot:
        """Return metadata, synchronously fetching only without a valid local copy."""
        validate_media_id(media_id)
        record = self.store.get_record(media_id)
        now = timezone.now()
        if record is None or record.fetched_at is None:
            if record is not None and self.store.error_cooldown_active(record, now=now):
                raise AnimeMetadataUnavailable(media_id)
            return self.store.refresh(media_id)

        snapshot = self.store.to_snapshot(record)
        if self.store.refresh_is_due(record, now=now):  # noqa: SIM102
            if self.store.claim_async_refresh(record, now=now):
                self.enqueue_refresh(record.media_id)
        return snapshot


class RefreshAnimeMetadata:
    """Application entry point for an explicitly requested provider refresh."""

    def __init__(self, store: MalAnimeMetadataStore | None = None) -> None:
        """Allow dependency injection while supplying the production MAL store."""
        self.store = store or MalAnimeMetadataStore()

    def execute(self, media_id: int) -> AnimeMetadataSnapshot:
        """Refresh MAL metadata through the store."""
        validate_media_id(media_id)
        return self.store.refresh(media_id)
