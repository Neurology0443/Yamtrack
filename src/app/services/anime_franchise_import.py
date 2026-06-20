"""Unified MAL anime franchise import orchestration."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, TypedDict

from django.contrib.auth import get_user_model
from django.db import transaction

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import mal
from app.services.anime_franchise_cache_warmer import (
    schedule_mal_anime_franchise_cache_warm,
)
from app.services.anime_franchise_discovery import AnimeFranchiseDiscoveryService
from app.services.anime_franchise_import_profiles import get_import_profile
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_import_state import AnimeImportStateService
from app.services.anime_series_view_refresh_triggers import (
    AnimeSeriesViewRefreshTriggerService,
)
from events.notifications import notify_entry_added_after_commit

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


CacheWarmKind = Literal["root", "detail"]


class CacheWarmTarget(TypedDict):
    """Registered cache warm target for an anime franchise import run."""

    media_id: str
    kind: CacheWarmKind
    component_root_mal_id: str


@dataclass
class FranchiseImportStats:
    """Counters collected during an anime franchise import run."""

    scanned: int = 0
    users_considered: int = 0
    distinct_seeds: int = 0
    due_selected: int = 0
    skipped_not_due: int = 0
    created: int = 0
    planned_creations: int = 0
    already_exists: int = 0
    state_rows_created: int = 0
    state_rows_updated: int = 0
    skipped: int = 0
    errors: int = 0
    created_ids: list[str] = field(default_factory=list)
    cache_warm_targets: list[CacheWarmTarget] = field(default_factory=list)
    cache_warm_roots: list[str] = field(default_factory=list)
    cache_warm_scheduled: int = 0
    cache_warm_errors: int = 0
    discovery_errors: int = 0


class AnimeFranchiseImportService:
    """Profile-driven importer backed by canonical franchise snapshots."""

    def __init__(
        self,
        *,
        snapshot_service: AnimeFranchiseSnapshotService | None = None,
        state_service: AnimeImportStateService | None = None,
        cache_warm_scheduler: Callable[[str], None] | None = None,
        discovery_service: AnimeFranchiseDiscoveryService | None = None,
        series_view_refresh_trigger: AnimeSeriesViewRefreshTriggerService | None = None,
    ):
        """Initialize the importer with optional testable dependencies."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()
        self.state_service = state_service or AnimeImportStateService()
        self.cache_warm_scheduler = (
            cache_warm_scheduler or schedule_mal_anime_franchise_cache_warm
        )
        self.discovery_service = discovery_service or AnimeFranchiseDiscoveryService()
        self.series_view_refresh_trigger = (
            series_view_refresh_trigger or AnimeSeriesViewRefreshTriggerService()
        )

    def run(  # noqa: C901, PLR0912, PLR0915
        self,
        *,
        profile_key: str,
        dry_run: bool,
        full_rescan: bool,
        limit: int | None,
        refresh_cache: bool,
        user_ids: list[int] | None,
    ) -> FranchiseImportStats:
        """Run the configured franchise import profile."""
        stats = FranchiseImportStats()
        profile = get_import_profile(profile_key)

        due_seeds, skipped_not_due = self.state_service.select_due_seeds(
            profile=profile,
            profile_key=profile_key,
            user_ids=user_ids,
            full_rescan=full_rescan,
            limit=limit,
        )
        stats.skipped_not_due = skipped_not_due
        stats.due_selected = len(due_seeds)
        stats.users_considered = len({seed.user_id for seed in due_seeds})
        stats.distinct_seeds = len({seed.seed_mal_id for seed in due_seeds})

        users_by_id = get_user_model().objects.in_bulk(
            {seed.user_id for seed in due_seeds}
        )

        baseline_roots_created_this_run: set[tuple[int, str]] = set()
        scheduled_warm_targets_by_media_id: dict[str, CacheWarmTarget] = {}

        def schedule_cache_warm_once(
            media_id: str,
            *,
            kind: CacheWarmKind,
            component_root_mal_id: str,
        ) -> None:
            media_id = str(media_id)
            component_root_mal_id = str(component_root_mal_id)

            if kind not in {"root", "detail"}:
                msg = f"Unsupported cache warm kind: {kind}"
                raise ValueError(msg)

            existing_target = scheduled_warm_targets_by_media_id.get(media_id)
            if existing_target is not None:
                if existing_target["kind"] == "detail" and kind == "root":
                    existing_target["kind"] = "root"
                    existing_target["component_root_mal_id"] = component_root_mal_id

                    if media_id not in stats.cache_warm_roots:
                        stats.cache_warm_roots.append(media_id)

                    logger.info(
                        "Anime franchise import promoted cache warm target to root "
                        "for media_id=%s component_root_mal_id=%s",
                        media_id,
                        component_root_mal_id,
                    )
                return

            try:
                # The existing warm scheduler is intentionally reused with non-root
                # media IDs so the build task can decide whether to create an alias,
                # a canonical local payload, or a scoped payload.
                self.cache_warm_scheduler(media_id)
            except Exception:
                stats.cache_warm_errors += 1
                logger.exception(
                    "Anime franchise import failed to register %s cache warm build "
                    "for media_id=%s component_root_mal_id=%s",
                    kind,
                    media_id,
                    component_root_mal_id,
                )
                return

            target: CacheWarmTarget = {
                "media_id": media_id,
                "kind": kind,
                "component_root_mal_id": component_root_mal_id,
            }
            scheduled_warm_targets_by_media_id[media_id] = target
            stats.cache_warm_targets.append(target)
            stats.cache_warm_scheduled += 1

            if kind == "root":
                stats.cache_warm_roots.append(media_id)

            logger.info(
                "Anime franchise import registered %s cache warm build "
                "for media_id=%s component_root_mal_id=%s",
                kind,
                media_id,
                component_root_mal_id,
            )

        for due_seed in due_seeds:
            stats.scanned += 1
            user = users_by_id.get(due_seed.user_id)
            if user is None:
                stats.skipped += 1
                logger.warning(
                    (
                        "Skipping MAL anime franchise import because user %s "
                        "does not exist"
                    ),
                    due_seed.user_id,
                )
                continue
            try:
                snapshot = self.snapshot_service.build(
                    due_seed.seed_mal_id,
                    refresh_cache=refresh_cache,
                )
                component_root_mal_id = str(profile.component_root_media_id(snapshot))
                selection = profile.select(snapshot)
                fingerprint = self.state_service.build_fingerprint(
                    profile_key,
                    selection.fingerprint_payload,
                )
                imported_media_ids_for_snapshot: set[str] = set()
                for raw_media_id in sorted(selection.media_ids, key=int):
                    media_id = str(raw_media_id)
                    exists = Anime.objects.filter(
                        user_id=due_seed.user_id,
                        item__media_id=media_id,
                        item__source=Sources.MAL.value,
                        item__media_type=MediaTypes.ANIME.value,
                    ).exists()
                    if exists:
                        stats.already_exists += 1
                        continue

                    stats.planned_creations += 1
                    if dry_run:
                        # In dry-run, treat planned imports as imported for discovery
                        # suppression so notification stats match a real run.
                        imported_media_ids_for_snapshot.add(media_id)
                        continue

                    metadata = mal.anime_minimal(
                        media_id,
                        refresh_cache=refresh_cache,
                    )
                    self._create_anime_entry(
                        user_id=due_seed.user_id,
                        media_id=media_id,
                        title=metadata["title"],
                        image=metadata["image"],
                        release_date_metadata=metadata,
                    )
                    stats.created += 1
                    stats.created_ids.append(media_id)
                    imported_media_ids_for_snapshot.add(media_id)
                    schedule_cache_warm_once(
                        component_root_mal_id,
                        kind="root",
                        component_root_mal_id=component_root_mal_id,
                    )

                    detail_warm_ids = profile.detail_cache_warm_media_ids(
                        snapshot,
                        {media_id},
                    )
                    for raw_detail_media_id in sorted(detail_warm_ids, key=int):
                        detail_media_id = str(raw_detail_media_id)
                        if detail_media_id == component_root_mal_id:
                            continue
                        schedule_cache_warm_once(
                            detail_media_id,
                            kind="detail",
                            component_root_mal_id=component_root_mal_id,
                        )

                if imported_media_ids_for_snapshot and not dry_run:
                    refresh_media_ids = {
                        *imported_media_ids_for_snapshot,
                        str(due_seed.seed_mal_id),
                        component_root_mal_id,
                    }
                    try:
                        self.series_view_refresh_trigger.schedule_import_batch(
                            user=user,
                            media_ids=refresh_media_ids,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to schedule Anime Series View refresh after import",
                            extra={
                                "user_id": user.id,
                                "seed_media_id": due_seed.seed_mal_id,
                                "media_ids": sorted(refresh_media_ids, key=int),
                            },
                        )

                root_key = (user.id, component_root_mal_id)
                force_baseline_suppression = root_key in baseline_roots_created_this_run
                try:
                    discovery_stats = self.discovery_service.process_snapshot(
                        user=user,
                        snapshot=snapshot,
                        component_root_mal_id=component_root_mal_id,
                        profile_key=profile_key,
                        imported_media_ids=imported_media_ids_for_snapshot,
                        dry_run=dry_run,
                        force_baseline_suppression=force_baseline_suppression,
                    )
                    if discovery_stats.baseline_created:
                        baseline_roots_created_this_run.add(root_key)
                    logger.info(
                        "Processed MAL anime franchise discoveries",
                        extra={
                            "user_id": due_seed.user_id,
                            "component_root_mal_id": component_root_mal_id,
                            "seed_media_id": due_seed.seed_mal_id,
                            "discovery_stats": asdict(discovery_stats),
                        },
                    )
                except Exception as exc:
                    stats.discovery_errors += 1
                    logger.exception(
                        "Failed to process MAL anime franchise discoveries",
                        extra={
                            "user_id": due_seed.user_id,
                            "component_root_mal_id": component_root_mal_id,
                            "seed_media_id": due_seed.seed_mal_id,
                        },
                    )
                    if not dry_run:
                        try:
                            self.discovery_service.record_error(
                                user=user,
                                component_root_mal_id=component_root_mal_id,
                                error=exc,
                            )
                        except Exception:
                            logger.exception(
                                "Failed to record MAL anime franchise discovery error",
                                extra={
                                    "user_id": due_seed.user_id,
                                    "component_root_mal_id": component_root_mal_id,
                                    "seed_media_id": due_seed.seed_mal_id,
                                },
                            )

                if dry_run:
                    continue

                _, state_created, _ = self.state_service.record_success(
                    user_id=due_seed.user_id,
                    seed_mal_id=due_seed.seed_mal_id,
                    profile_key=profile_key,
                    fingerprint=fingerprint,
                    component_root_mal_id=component_root_mal_id,
                    component_size=len(snapshot.continuity_component),
                )
                if state_created:
                    stats.state_rows_created += 1
                else:
                    stats.state_rows_updated += 1

            except Exception:  # noqa: BLE001
                stats.errors += 1
                if not dry_run:
                    _, state_created = self.state_service.record_error(
                        user_id=due_seed.user_id,
                        seed_mal_id=due_seed.seed_mal_id,
                        profile_key=profile_key,
                    )
                    if state_created:
                        stats.state_rows_created += 1
                    else:
                        stats.state_rows_updated += 1

        return stats

    @transaction.atomic
    def _create_anime_entry(
        self,
        *,
        user_id: int,
        media_id: str,
        title: str,
        image: str,
        release_date_metadata: dict | None = None,
    ) -> None:
        item, _ = Item.objects.get_or_create(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            defaults={
                "title": title,
                "image": image,
            },
        )
        anime = Anime(
            user_id=user_id,
            item=item,
            status=Status.PLANNING.value,
        )
        anime._skip_hot_priority = True
        anime.save()
        from events.services.anime_release_date_notifications import (  # noqa: PLC0415
            AnimeReleaseDateNotificationService,
        )

        try:
            release_date_service = AnimeReleaseDateNotificationService()
            release_date_service.initialize_or_prioritize_imported_item(
                item=item,
                metadata=release_date_metadata or {},
            )
        except Exception:
            logger.exception(
                "Failed to initialize anime release-date state for media_id=%s",
                media_id,
            )
        notify_entry_added_after_commit(
            user_id=user_id,
            media_label=str(anime),
        )
