"""Temporary shared MAL hydration for one anime franchise build operation."""

from __future__ import annotations

from django.conf import settings

from app.providers import mal
from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_mal_metadata import anime_minimal_from_metadata


class AnimeFranchiseHydrationContext:
    """Memoize MAL anime detail hydration for the lifetime of one operation."""

    FETCH_LEVEL_STALE_ALLOWED = 1
    FETCH_LEVEL_NORMAL = 2
    FETCH_LEVEL_REFRESHED = 3

    def __init__(self, *, anime_fetcher=None):
        """Create a context backed by the provided fetcher or mal.anime."""
        self.anime_fetcher = anime_fetcher or mal.anime
        self._metadata_by_media_id = {}
        self._fetch_level_by_media_id = {}

    def _required_fetch_level(self, *, refresh_cache, allow_stale):
        """Return the minimum session-local freshness level for the request."""
        if refresh_cache:
            return self.FETCH_LEVEL_REFRESHED
        if allow_stale:
            return self.FETCH_LEVEL_STALE_ALLOWED
        return self.FETCH_LEVEL_NORMAL

    def fetch_anime(
        self,
        media_id,
        *,
        refresh_cache=False,
        allow_stale=False,
        schedule_stale_refresh=False,
    ):
        """Fetch one MAL anime payload, reusing sufficiently fresh results."""
        media_id = str(media_id)
        required_level = self._required_fetch_level(
            refresh_cache=refresh_cache,
            allow_stale=allow_stale,
        )
        current_level = self._fetch_level_by_media_id.get(media_id)
        if current_level is not None and current_level >= required_level:
            return self._metadata_by_media_id[media_id]

        metadata = self.anime_fetcher(
            media_id,
            refresh_cache=refresh_cache,
            allow_stale=allow_stale,
            schedule_stale_refresh=schedule_stale_refresh,
        )
        self._metadata_by_media_id[media_id] = metadata
        self._fetch_level_by_media_id[media_id] = required_level
        return metadata


class AnimeFranchiseBuildSession:
    """Factory for existing franchise services sharing one MAL hydration context."""

    def __init__(self, *, refresh_cache=False, max_nodes=None, hydration_context=None):
        """Create a build session with shared hydration options."""
        self.refresh_cache = refresh_cache
        self.max_nodes = (
            max_nodes if max_nodes is not None else settings.ANIME_FRANCHISE_MAX_NODES
        )
        self.hydration_context = hydration_context or AnimeFranchiseHydrationContext()

    @property
    def metadata_fetcher(self):
        """Return the memoized MAL metadata fetcher."""
        return self.hydration_context.fetch_anime

    def fetch_anime(self, media_id, *, refresh_cache=None):
        """Fetch full MAL anime metadata using the session refresh default."""
        if refresh_cache is None:
            refresh_cache = self.refresh_cache
        return self.hydration_context.fetch_anime(
            media_id,
            refresh_cache=refresh_cache,
        )

    def anime_minimal(self, media_id, *, refresh_cache=None):
        """Return minimal MAL anime metadata without issuing a separate fetch."""
        metadata = self.fetch_anime(media_id, refresh_cache=refresh_cache)
        return anime_minimal_from_metadata(metadata)

    def graph_builder(self):
        """Create a graph builder using the session fetcher."""
        return AnimeFranchiseGraphBuilder(
            metadata_fetcher=self.metadata_fetcher,
            refresh_cache=self.refresh_cache,
            max_nodes=self.max_nodes,
        )

    def snapshot_service(self):
        """Create a snapshot service using a session graph builder."""
        return AnimeFranchiseSnapshotService(graph_builder=self.graph_builder())

    def build_snapshot(self, media_id, **kwargs):
        """Build one snapshot with the session default refresh policy."""
        kwargs.setdefault("refresh_cache", self.refresh_cache)
        return self.snapshot_service().build(media_id, **kwargs)

    def build_series_view_snapshot_service(self):
        """Create a snapshot service for Anime Series View projections."""
        return self.snapshot_service()
