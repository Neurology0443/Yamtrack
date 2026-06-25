"""Orchestrate MAL anime franchise maintenance consumers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models import Anime, MediaTypes, Sources
from app.services.anime_franchise_build_session import AnimeFranchiseBuildSession
from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService
from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryService
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshService,
)
from app.services.anime_series_view_projection import AnimeSeriesViewProjectionBuilder

logger = logging.getLogger(__name__)


@dataclass
class AnimeFranchiseMaintenanceResult:
    """Structured result for one maintained franchise seed."""

    user_id: int
    seed_mal_id: str
    component_root_mal_id: str = ""
    snapshot_built: bool = False
    cache_attempted: bool = False
    cache_built: bool = False
    discovery_attempted: bool = False
    discovery_processed: bool = False
    series_view_attempted: bool = False
    series_view_refreshed: bool = False
    changed: bool = False
    fingerprint: str = ""
    tracked_member_media_ids: tuple[str, ...] = ()
    errors: list[str] = field(default_factory=list)


class AnimeFranchiseMaintenanceService:
    """Orchestrate MAL franchise maintenance consumers with one shared build session."""

    def __init__(
        self,
        *,
        discovery_service=None,
        cache_build_service_factory=None,
        series_view_refresh_service_factory=None,
    ):
        """Initialize orchestration dependencies."""
        self.discovery_service = discovery_service or AnimeFranchiseDiscoveryService()
        self.cache_build_service_factory = cache_build_service_factory or (
            lambda build_session: AnimeFranchiseCacheBuildService(
                build_session=build_session
            )
        )
        self.series_view_refresh_service_factory = series_view_refresh_service_factory

    def process_seed(
        self,
        *,
        user,
        seed_mal_id,
        refresh_cache: bool,
        update_ui_cache: bool = True,
        process_discovery: bool = True,
        refresh_series_view: bool = False,
        refresh_series_view_on_change: bool = True,
        previous_fingerprint: str = "",
        imported_media_ids: set[str] | None = None,
        profile_key: str | None = None,
        force_baseline_suppression: bool = False,
    ) -> AnimeFranchiseMaintenanceResult:
        """Process one tracked seed through cache, discovery, and Series View paths."""
        seed_mal_id = str(seed_mal_id).strip()
        result = AnimeFranchiseMaintenanceResult(
            user_id=user.id, seed_mal_id=seed_mal_id
        )
        build_session = AnimeFranchiseBuildSession(refresh_cache=refresh_cache)
        snapshot_service = build_session.snapshot_service()
        snapshot = snapshot_service.build(seed_mal_id, refresh_cache=refresh_cache)
        result.snapshot_built = True
        result.component_root_mal_id = str(snapshot.canonical_root_media_id)
        result.fingerprint = self.discovery_service.build_snapshot_fingerprint(snapshot)
        result.changed = bool(
            previous_fingerprint and previous_fingerprint != result.fingerprint
        )
        result.tracked_member_media_ids = self._tracked_member_media_ids(user, snapshot)

        if update_ui_cache:
            result.cache_attempted = True
            try:
                cache_result = self.cache_build_service_factory(
                    build_session
                ).build_and_save_from_snapshot(
                    seed_mal_id,
                    snapshot=snapshot,
                    graph_builder=snapshot_service.graph_builder,
                    force_cache_rebuild=True,
                )
                result.cache_built = bool(cache_result.get("built"))
                if not result.cache_built and cache_result.get("error"):
                    result.errors.append(str(cache_result.get("error"))[:250])
            except Exception as error:
                logger.exception(
                    "Maintenance cache update failed",
                    extra={"user_id": user.id, "seed_mal_id": seed_mal_id},
                )
                result.errors.append(str(error)[:250])

        if process_discovery:
            result.discovery_attempted = True
            try:
                self.discovery_service.process_snapshot(
                    user=user,
                    snapshot=snapshot,
                    component_root_mal_id=result.component_root_mal_id,
                    profile_key=profile_key,
                    imported_media_ids=imported_media_ids or set(),
                    dry_run=False,
                    force_baseline_suppression=force_baseline_suppression,
                )
                result.discovery_processed = True
            except Exception as error:
                logger.exception(
                    "Maintenance discovery processing failed",
                    extra={"user_id": user.id, "seed_mal_id": seed_mal_id},
                )
                result.errors.append(str(error)[:250])

        should_refresh_series_view = refresh_series_view or (
            refresh_series_view_on_change and result.changed
        )
        if should_refresh_series_view:
            result.series_view_attempted = True
            try:
                refresh_service = self._series_view_refresh_service(build_session)
                stats = refresh_service.refresh_for_media_ids(
                    user=user,
                    media_ids=result.tracked_member_media_ids or (seed_mal_id,),
                    refresh_cache=refresh_cache,
                )
                result.series_view_refreshed = stats.errors == 0
                if stats.errors:
                    result.errors.append(f"series_view_errors={stats.errors}")
            except Exception as error:
                logger.exception(
                    "Maintenance Series View refresh failed",
                    extra={"user_id": user.id, "seed_mal_id": seed_mal_id},
                )
                result.errors.append(str(error)[:250])

        return result

    def _series_view_refresh_service(self, build_session):
        if self.series_view_refresh_service_factory is not None:
            return self.series_view_refresh_service_factory(build_session)
        projection_builder = AnimeSeriesViewProjectionBuilder(
            snapshot_service=build_session.build_series_view_snapshot_service(),
        )
        return AnimeSeriesViewFranchiseRefreshService(
            projection_builder=projection_builder
        )

    def _tracked_member_media_ids(self, user, snapshot) -> tuple[str, ...]:
        component_ids = {str(node.media_id) for node in snapshot.continuity_component}
        component_ids.add(str(snapshot.canonical_root_media_id))
        component_ids.add(str(snapshot.root_node.media_id))
        tracked_ids = Anime.objects.filter(
            user=user,
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
            item__media_id__in=component_ids,
        ).values_list("item__media_id", flat=True)
        return tuple(sorted({str(media_id) for media_id in tracked_ids}))
