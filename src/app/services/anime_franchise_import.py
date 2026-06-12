"""Unified MAL anime franchise import orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.db import transaction

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import mal
from app.services.anime_franchise_cache_warmer import (
    schedule_mal_anime_franchise_cache_warm,
)
from app.services.anime_franchise_import_profiles import get_import_profile
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_import_state import AnimeImportStateService
from events.notifications import notify_entry_added_after_commit

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


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
    cache_warm_roots: list[str] = field(default_factory=list)
    cache_warm_scheduled: int = 0
    cache_warm_errors: int = 0


class AnimeFranchiseImportService:
    """Profile-driven importer backed by canonical franchise snapshots."""

    def __init__(
        self,
        *,
        snapshot_service: AnimeFranchiseSnapshotService | None = None,
        state_service: AnimeImportStateService | None = None,
        cache_warm_scheduler: Callable[[str], bool | None] | None = None,
    ):
        """Initialize the importer with optional testable dependencies."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()
        self.state_service = state_service or AnimeImportStateService()
        self.cache_warm_scheduler = (
            cache_warm_scheduler or schedule_mal_anime_franchise_cache_warm
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

        roots_to_warm: set[str] = set()
        created_ids_by_root: dict[str, list[str]] = {}

        for due_seed in due_seeds:
            stats.scanned += 1
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
                    )
                    stats.created += 1
                    stats.created_ids.append(media_id)
                    roots_to_warm.add(component_root_mal_id)
                    created_ids_by_root.setdefault(component_root_mal_id, []).append(
                        media_id
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

        for root_media_id in sorted(roots_to_warm, key=int):
            created_ids = sorted(
                set(created_ids_by_root.get(root_media_id, [])),
                key=int,
            )
            try:
                scheduled = self.cache_warm_scheduler(root_media_id)
            except Exception:
                stats.cache_warm_errors += 1
                logger.exception(
                    "Anime franchise import failed to schedule cache warm build "
                    "for component_root_mal_id=%s created_ids=%s",
                    root_media_id,
                    created_ids,
                )
                continue

            if not scheduled:
                stats.cache_warm_errors += 1
                logger.warning(
                    "Anime franchise import did not schedule cache warm build "
                    "for component_root_mal_id=%s created_ids=%s",
                    root_media_id,
                    created_ids,
                )
                continue

            stats.cache_warm_roots.append(root_media_id)
            stats.cache_warm_scheduled += 1
            logger.info(
                "Anime franchise import scheduled cache warm build "
                "for component_root_mal_id=%s created_ids=%s",
                root_media_id,
                created_ids,
            )

        return stats

    @transaction.atomic
    def _create_anime_entry(
        self, *, user_id: int, media_id: str, title: str, image: str
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
        notify_entry_added_after_commit(
            user_id=user_id,
            media_label=str(anime),
        )
