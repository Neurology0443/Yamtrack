"""Unified MAL anime franchise import orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import mal
from app.services.anime_franchise_import_profiles import get_import_profile
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_import_state import AnimeImportStateService


@dataclass
class FranchiseImportStats:
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


class AnimeFranchiseImportService:
    """Profile-driven importer backed by canonical franchise snapshots."""

    def __init__(
        self,
        *,
        snapshot_service: AnimeFranchiseSnapshotService | None = None,
        state_service: AnimeImportStateService | None = None,
    ):
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()
        self.state_service = state_service or AnimeImportStateService()

    def run(
        self,
        *,
        profile_key: str,
        dry_run: bool,
        full_rescan: bool,
        limit: int | None,
        refresh_cache: bool,
        user_ids: list[int] | None,
    ) -> FranchiseImportStats:
        stats = FranchiseImportStats()
        profile = get_import_profile(profile_key)

        due_seeds, skipped_not_due = self.state_service.select_due_seeds(
            profile_key=profile_key,
            user_ids=user_ids,
            full_rescan=full_rescan,
            limit=limit,
        )
        stats.skipped_not_due = skipped_not_due
        stats.due_selected = len(due_seeds)
        stats.users_considered = len({seed.user_id for seed in due_seeds})
        stats.distinct_seeds = len({seed.seed_mal_id for seed in due_seeds})

        for due_seed in due_seeds:
            stats.scanned += 1
            try:
                snapshot = self.snapshot_service.build(
                    due_seed.seed_mal_id,
                    refresh_cache=refresh_cache,
                )
                selection = profile.select(snapshot)
                fingerprint = self.state_service.build_fingerprint(
                    profile_key,
                    selection.fingerprint_payload,
                )

                for media_id in sorted(selection.media_ids, key=int):
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

                if dry_run:
                    continue

                _, state_created, _ = self.state_service.record_success(
                    user_id=due_seed.user_id,
                    seed_mal_id=due_seed.seed_mal_id,
                    profile_key=profile_key,
                    fingerprint=fingerprint,
                    component_root_mal_id=snapshot.root_node.media_id,
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
    def _create_anime_entry(self, *, user_id: int, media_id: str, title: str, image: str) -> None:
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
