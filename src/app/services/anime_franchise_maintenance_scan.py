"""Persistent scheduler for autonomous MAL anime franchise maintenance."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from app.models import (
    Anime,
    AnimeFranchiseMaintenanceScanState,
    MediaTypes,
    Sources,
    Status,
)
from app.services.anime_franchise_maintenance import AnimeFranchiseMaintenanceService

logger = logging.getLogger(__name__)

ELIGIBLE_STATUSES = [
    Status.PLANNING.value,
    Status.IN_PROGRESS.value,
    Status.COMPLETED.value,
]


@dataclass
class AnimeFranchiseMaintenanceScanStats:
    """Counters produced by one maintenance scan batch."""

    tracked_seeds_seen: int = 0
    states_created: int = 0
    due_selected: int = 0
    processed: int = 0
    skipped_not_due: int = 0
    skipped_not_tracked: int = 0
    skipped_duplicate_root: int = 0
    cache_built: int = 0
    discovery_processed: int = 0
    series_view_refreshed: int = 0
    changed: int = 0
    errors: int = 0
    backlog: int = 0

    def to_dict(self):
        """Return JSON-serializable counters."""
        return asdict(self)


class AnimeFranchiseMaintenanceScanService:
    """Manage scan state, due selection, jitter/backoff, and orchestration calls."""

    def __init__(self, *, maintenance_service=None):
        """Initialize with an optional maintenance orchestrator."""
        self.maintenance_service = (
            maintenance_service or AnimeFranchiseMaintenanceService()
        )

    def scan_due(self, *, limit=None) -> AnimeFranchiseMaintenanceScanStats:
        """Create missing states and process a bounded batch of due seeds."""
        now = timezone.now()
        stats = AnimeFranchiseMaintenanceScanStats()
        stats.states_created = self.ensure_states(now=now)
        stats.tracked_seeds_seen = self._eligible_anime_queryset().count()
        batch_size = limit or settings.ANIME_FRANCHISE_MAINTENANCE_SCAN_BATCH_SIZE
        due_qs = AnimeFranchiseMaintenanceScanState.objects.filter(
            next_scan_at__lte=now,
        ).order_by("next_scan_at", "user_id", "seed_mal_id")
        stats.backlog = due_qs.count()
        states = list(due_qs.select_related("user")[:batch_size])
        stats.due_selected = len(states)
        processed_roots_by_user = set()

        for state in states:
            if not self._is_seed_tracked(state):
                stats.skipped_not_tracked += 1
                self._push_state_forward(state, now=now)
                continue
            if state.component_root_mal_id:
                root_key = (state.user_id, state.component_root_mal_id)
                if root_key in processed_roots_by_user:
                    stats.skipped_duplicate_root += 1
                    self._mark_duplicate_covered(state, now=now)
                    continue
            try:
                result = self.maintenance_service.process_seed(
                    user=state.user,
                    seed_mal_id=state.seed_mal_id,
                    refresh_cache=settings.ANIME_FRANCHISE_MAINTENANCE_REFRESH_CACHE,
                    update_ui_cache=True,
                    process_discovery=True,
                    refresh_series_view=False,
                    refresh_series_view_on_change=(
                        settings.ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_CHANGE
                    ),
                    previous_fingerprint=state.last_result_fingerprint,
                )
            except Exception as error:
                logger.exception(
                    "MAL anime franchise maintenance scan failed",
                    extra={"user_id": state.user_id, "seed_mal_id": state.seed_mal_id},
                )
                stats.errors += 1
                self._mark_error(state, error=error, now=now)
                continue

            stats.processed += 1
            stats.cache_built += int(result.cache_built)
            stats.discovery_processed += int(result.discovery_processed)
            stats.series_view_refreshed += int(result.series_view_refreshed)
            stats.changed += int(result.changed)
            if result.errors:
                stats.errors += 1
            self._mark_success(state, result=result, now=now)
            if result.component_root_mal_id:
                processed_roots_by_user.add(
                    (state.user_id, result.component_root_mal_id)
                )
            self._cover_tracked_member_states(state, result=result, now=now)
        return stats

    def ensure_states(self, *, now=None) -> int:
        """Ensure every eligible tracked MAL anime has a maintenance state."""
        now = now or timezone.now()
        created = 0
        for user_id, raw_seed_mal_id in (
            self._eligible_anime_queryset()
            .values_list("user_id", "item__media_id")
            .distinct()
        ):
            seed_mal_id = str(raw_seed_mal_id)
            try:
                _, was_created = (
                    AnimeFranchiseMaintenanceScanState.objects.get_or_create(
                        user_id=user_id,
                        seed_mal_id=seed_mal_id,
                        defaults={
                            "next_scan_at": now
                            + self._spread_delta(
                                user_id,
                                seed_mal_id,
                                "initial",
                                settings.ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS,
                            )
                        },
                    )
                )
            except IntegrityError:
                was_created = False
            created += int(was_created)
        return created

    def mark_component_root_due_soon(self, component_root_mal_id: str) -> int:
        """Nudge known states for a continuity root into a near-future scan."""
        component_root_mal_id = str(component_root_mal_id).strip()
        if not component_root_mal_id:
            return 0
        now = timezone.now()
        changed = 0
        for state in AnimeFranchiseMaintenanceScanState.objects.filter(
            component_root_mal_id=component_root_mal_id
        ):
            due_at = now + self._spread_minutes(
                state.user_id, state.seed_mal_id, "due-soon", 5, 60
            )
            if state.next_scan_at > due_at:
                state.next_scan_at = due_at
                state.save(update_fields=["next_scan_at", "updated_at"])
                changed += 1
        return changed

    def _eligible_anime_queryset(self):
        return Anime.objects.select_related("item").filter(
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
            status__in=ELIGIBLE_STATUSES,
        )

    def _is_seed_tracked(self, state) -> bool:
        return (
            self._eligible_anime_queryset()
            .filter(user_id=state.user_id, item__media_id=state.seed_mal_id)
            .exists()
        )

    def _mark_success(self, state, *, result, now):
        changed = bool(
            state.last_result_fingerprint
            and state.last_result_fingerprint != result.fingerprint
        )
        state.component_root_mal_id = result.component_root_mal_id
        state.last_scanned_at = now
        state.last_success_at = now
        state.last_error_at = None
        state.last_error = ""
        state.consecutive_error_count = 0
        state.consecutive_stable_scans = (
            0 if changed else state.consecutive_stable_scans + 1
        )
        if changed:
            state.last_change_at = now
        state.last_result_fingerprint = result.fingerprint
        state.next_scan_at = self._next_success_scan_at(state, now=now)
        state.save()

    def _mark_duplicate_covered(self, state, *, now):
        state.last_scanned_at = now
        state.next_scan_at = self._next_success_scan_at(state, now=now)
        state.save(update_fields=["last_scanned_at", "next_scan_at", "updated_at"])

    def _push_state_forward(self, state, *, now):
        state.next_scan_at = now + self._spread_delta(
            state.user_id,
            state.seed_mal_id,
            "not-tracked",
            settings.ANIME_FRANCHISE_MAINTENANCE_TARGET_SWEEP_HOURS,
        )
        state.save(update_fields=["next_scan_at", "updated_at"])

    def _mark_error(self, state, *, error, now):
        state.last_scanned_at = now
        state.last_error_at = now
        state.last_error = (str(error) or error.__class__.__name__)[:500]
        state.consecutive_error_count += 1
        state.next_scan_at = now + self._spread_delta(
            state.user_id,
            state.seed_mal_id,
            f"error:{state.consecutive_error_count}",
            settings.ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS,
        )
        state.save()

    def _cover_tracked_member_states(self, state, *, result, now):
        for media_id in result.tracked_member_media_ids:
            member_state, _created = (
                AnimeFranchiseMaintenanceScanState.objects.get_or_create(
                    user_id=state.user_id,
                    seed_mal_id=media_id,
                    defaults={
                        "next_scan_at": self._next_success_scan_at(state, now=now)
                    },
                )
            )
            member_state.component_root_mal_id = result.component_root_mal_id
            if member_state.next_scan_at <= now and member_state.pk != state.pk:
                member_state.last_scanned_at = now
                member_state.next_scan_at = self._next_success_scan_at(
                    member_state, now=now
                )
            member_state.save(
                update_fields=[
                    "component_root_mal_id",
                    "last_scanned_at",
                    "next_scan_at",
                    "updated_at",
                ]
            )

    def _next_success_scan_at(self, state, *, now):
        hours = settings.ANIME_FRANCHISE_MAINTENANCE_TARGET_SWEEP_HOURS
        if settings.ANIME_FRANCHISE_MAINTENANCE_USE_STABLE_BACKOFF:
            days = min(
                2 ** max(state.consecutive_stable_scans - 1, 0),
                settings.ANIME_FRANCHISE_MAINTENANCE_MAX_STABLE_BACKOFF_DAYS,
            )
            hours = max(hours, days * 24)
        return now + self._spread_delta(
            state.user_id, state.seed_mal_id, "sweep", hours
        )

    def _spread_delta(self, user_id, seed_mal_id, purpose, hours):
        minutes = max(1, int(hours * 60))
        return timedelta(
            minutes=self._hash_int(user_id, seed_mal_id, purpose) % minutes
        )

    def _spread_minutes(self, user_id, seed_mal_id, purpose, min_minutes, max_minutes):
        span = max_minutes - min_minutes + 1
        return timedelta(
            minutes=min_minutes + (self._hash_int(user_id, seed_mal_id, purpose) % span)
        )

    def _hash_int(self, user_id, seed_mal_id, purpose):
        digest = hashlib.sha256(
            f"{user_id}:{seed_mal_id}:{purpose}".encode()
        ).hexdigest()
        return int(digest[:12], 16)
