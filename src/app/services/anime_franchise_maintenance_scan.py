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
from app.services.anime_franchise_maintenance_cadence import (
    ScanWindow,
    compute_success_scan_window,
)

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
    succeeded: int = 0
    partial_failed: int = 0
    failed: int = 0
    skipped_not_due: int = 0
    skipped_not_tracked: int = 0
    skipped_duplicate_root: int = 0
    cache_built: int = 0
    discovery_processed: int = 0
    series_view_refreshed: int = 0
    changed: int = 0
    errors: int = 0
    partial_failures: int = 0
    critical_errors: int = 0
    non_critical_errors: int = 0
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

    def scan_due(self, *, limit=None) -> AnimeFranchiseMaintenanceScanStats:  # noqa: C901, PLR0915
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
        processed_results_by_root = {}
        covered_seed_keys = set()
        covered_results_by_seed = {}

        for state in states:
            seed_key = (state.user_id, state.seed_mal_id)
            if seed_key in covered_seed_keys:
                stats.skipped_duplicate_root += 1
                self._mark_duplicate_covered(
                    state,
                    now=now,
                    result=covered_results_by_seed.get(seed_key),
                )
                continue
            if not self._is_seed_tracked(state):
                stats.skipped_not_tracked += 1
                self._push_state_forward(state, now=now)
                continue
            if state.component_root_mal_id:
                root_key = (state.user_id, state.component_root_mal_id)
                if root_key in processed_roots_by_user:
                    stats.skipped_duplicate_root += 1
                    result = processed_results_by_root.get(root_key)
                    self._mark_duplicate_covered(state, now=now, result=result)
                    covered_seed_keys.add(seed_key)
                    if result is not None:
                        covered_results_by_seed[seed_key] = result
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
                    refresh_series_view_on_success=(
                        settings.ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_SUCCESS
                    ),
                    previous_fingerprint=state.last_result_fingerprint,
                    previous_component_root_mal_id=state.component_root_mal_id,
                    last_success_at=state.last_success_at,
                )
            except Exception as error:
                logger.exception(
                    "MAL anime franchise maintenance scan failed",
                    extra={"user_id": state.user_id, "seed_mal_id": state.seed_mal_id},
                )
                stats.errors += 1
                stats.critical_errors += 1
                stats.failed += 1
                self._mark_error(state, error=error, now=now)
                continue

            stats.processed += 1
            stats.cache_built += int(result.cache_built)
            stats.discovery_processed += int(result.discovery_processed)
            stats.series_view_refreshed += int(result.series_view_refreshed)
            stats.changed += int(result.changed or result.root_changed)
            stats.non_critical_errors += int(bool(result.non_critical_errors))
            if result.critical_errors:
                stats.errors += 1
                stats.partial_failures += 1
                stats.partial_failed += 1
                stats.critical_errors += 1
                self._mark_partial_failure(state, result=result, now=now)
                continue

            stats.succeeded += 1
            self._mark_success(state, result=result, now=now)
            covered_seed_keys.add(seed_key)
            covered_results_by_seed[seed_key] = result
            for media_id in result.tracked_member_media_ids:
                member_seed_key = (state.user_id, str(media_id))
                covered_seed_keys.add(member_seed_key)
                covered_results_by_seed[member_seed_key] = result
            if result.component_root_mal_id:
                root_key = (state.user_id, result.component_root_mal_id)
                processed_roots_by_user.add(root_key)
                processed_results_by_root[root_key] = result
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
        return self._mark_states_due_soon(
            AnimeFranchiseMaintenanceScanState.objects.filter(
                component_root_mal_id=component_root_mal_id
            )
        )

    def mark_media_due_soon(self, media_id: str) -> int:
        """Nudge known states for a media ID or its resolved component root."""
        media_id = str(media_id or "").strip()
        if not media_id:
            return 0

        changed = 0
        states = list(
            AnimeFranchiseMaintenanceScanState.objects.filter(seed_mal_id=media_id)
        )
        roots_to_nudge = {
            state.component_root_mal_id
            for state in states
            if state.component_root_mal_id
        }
        # Fallback: media_id may itself be a component_root_mal_id.
        roots_to_nudge.add(media_id)

        seed_states_without_root = [
            state for state in states if not state.component_root_mal_id
        ]
        if seed_states_without_root:
            changed += self._mark_states_due_soon(seed_states_without_root)

        for component_root_mal_id in sorted(roots_to_nudge):
            changed += self.mark_component_root_due_soon(component_root_mal_id)

        return changed

    def _mark_states_due_soon(self, states) -> int:
        """Nudge states into a near-future scan without delaying closer scans."""
        now = timezone.now()
        changed = 0
        for state in states:
            due_at = self._due_soon_at(state, now=now)
            if state.next_scan_at > due_at:
                state.next_scan_at = due_at
                state.save(update_fields=["next_scan_at", "updated_at"])
                changed += 1
        return changed

    def _due_soon_at(self, state, *, now):
        """Return the deterministic near-future scan time for a state."""
        return now + self._spread_minutes(
            state.user_id, state.seed_mal_id, "due-soon", 5, 60
        )

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
            and state.last_result_fingerprint != result.maintenance_fingerprint
        )
        root_changed = bool(state.component_root_mal_id) and (
            state.component_root_mal_id != result.component_root_mal_id
        )
        state.component_root_mal_id = result.component_root_mal_id
        state.last_scanned_at = now
        state.last_success_at = now
        state.last_error_at = None
        state.last_error = ""
        state.consecutive_error_count = 0
        if changed or root_changed:
            state.last_change_at = now
            state.consecutive_stable_scans = 0
        else:
            state.consecutive_stable_scans += 1
        state.last_result_fingerprint = result.maintenance_fingerprint
        window = compute_success_scan_window(
            activity_summary=result.activity_summary,
            state=state,
            result=result,
            now=now,
        )
        result.scan_window = window
        result.cadence_profile = window.profile
        result.cadence_reason = window.reason
        state.next_scan_at = self._next_success_scan_at(
            state, result=result, window=window, now=now
        )
        state.save()
        self._log_success_cadence(state, result=result, window=window)

    def _mark_partial_failure(self, state, *, result, now):
        state.last_scanned_at = now
        state.last_error_at = now
        state.last_error = "; ".join(result.critical_errors)[:500]
        state.consecutive_error_count += 1
        state.next_scan_at = self._next_error_scan_at(state, now=now)
        state.save()

    def _mark_duplicate_covered(self, state, *, now, result=None):
        if result is None:
            state.last_scanned_at = now
            state.next_scan_at = self._next_success_scan_at(state, now=now)
            state.save(update_fields=["last_scanned_at", "next_scan_at", "updated_at"])
            return
        changed = bool(
            state.last_result_fingerprint
            and state.last_result_fingerprint != result.maintenance_fingerprint
        )
        root_changed = bool(state.component_root_mal_id) and (
            state.component_root_mal_id != result.component_root_mal_id
        )
        state.component_root_mal_id = result.component_root_mal_id
        state.last_scanned_at = now
        state.last_success_at = now
        state.last_error_at = None
        state.last_error = ""
        state.consecutive_error_count = 0
        if changed or root_changed:
            state.last_change_at = now
            state.consecutive_stable_scans = 0
        else:
            state.consecutive_stable_scans += 1
        state.last_result_fingerprint = result.maintenance_fingerprint
        window = compute_success_scan_window(
            activity_summary=result.activity_summary,
            state=state,
            result=result,
            now=now,
        )
        result.scan_window = window
        result.cadence_profile = window.profile
        result.cadence_reason = window.reason
        state.next_scan_at = self._next_success_scan_at(
            state, result=result, window=window, now=now
        )
        state.save()
        self._log_success_cadence(state, result=result, window=window)

    def _push_state_forward(self, state, *, now):
        state.next_scan_at = self._next_success_scan_at(
            state,
            window=ScanWindow(
                profile="COOL",
                reason="not_tracked",
                min_minutes=3 * 24 * 60,
                max_minutes=10 * 24 * 60,
                micro_jitter_minutes=240,
            ),
            now=now,
        )
        state.save(update_fields=["next_scan_at", "updated_at"])

    def _mark_error(self, state, *, error, now):
        state.last_scanned_at = now
        state.last_error_at = now
        state.last_error = (str(error) or error.__class__.__name__)[:500]
        state.consecutive_error_count += 1
        state.next_scan_at = self._next_error_scan_at(state, now=now)
        state.save()

    def _cover_tracked_member_states(self, state, *, result, now):
        tracked_ids = self._tracked_seed_ids_for_user(
            user_id=state.user_id,
            media_ids=result.tracked_member_media_ids,
        )
        for media_id in tracked_ids:
            member_state, _created = (
                AnimeFranchiseMaintenanceScanState.objects.get_or_create(
                    user_id=state.user_id,
                    seed_mal_id=media_id,
                    defaults={
                        "next_scan_at": self._next_success_scan_at(
                            state,
                            result=result,
                            window=getattr(result, "scan_window", None),
                            now=now,
                        )
                    },
                )
            )
            self._mark_duplicate_covered(member_state, result=result, now=now)

    def _tracked_seed_ids_for_user(self, *, user_id, media_ids):
        normalized_ids = {
            str(media_id).strip()
            for media_id in media_ids
            if media_id is not None and str(media_id).strip()
        }
        if not normalized_ids:
            return set()
        return {
            str(media_id)
            for media_id in self._eligible_anime_queryset()
            .filter(user_id=user_id, item__media_id__in=normalized_ids)
            .values_list("item__media_id", flat=True)
        }

    def _next_success_scan_at(self, state, *, result=None, window=None, now):
        if window is None:
            window = ScanWindow(
                profile="WARM",
                reason="fallback",
                min_minutes=24 * 60,
                max_minutes=3 * 24 * 60,
                micro_jitter_minutes=120,
            )
        key, has_root = self._schedule_key(state, result=result)
        due_at = now + self._spread_minutes(
            state.user_id,
            key,
            f"sweep:{window.profile}:{window.reason}",
            window.min_minutes,
            window.max_minutes,
        )
        if has_root and window.micro_jitter_minutes > 0:
            due_at += self._spread_signed_minutes(
                state.user_id,
                f"{key}:seed:{state.seed_mal_id}",
                f"micro:{window.profile}:{window.reason}",
                window.micro_jitter_minutes,
            )
        return self._clamp_datetime(
            due_at,
            minimum=now + timedelta(minutes=window.min_minutes),
            maximum=now + timedelta(minutes=window.max_minutes),
        )

    def _schedule_key(self, state, *, result=None) -> tuple[str, bool]:
        root_id = ""
        if result is not None:
            root_id = str(getattr(result, "component_root_mal_id", "") or "").strip()
        if not root_id:
            root_id = str(state.component_root_mal_id or "").strip()
        if root_id:
            return f"root:{root_id}", True
        return f"seed:{state.seed_mal_id}", False

    def _next_error_scan_at(self, state, *, now):
        base_hours = settings.ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS
        multiplier = 2 ** min(max(state.consecutive_error_count - 1, 0), 5)
        hours = min(base_hours * multiplier, 24 * 7)
        minimum_minutes = 30
        max_minutes = max(minimum_minutes, int(hours * 60))
        return now + self._spread_minutes(
            state.user_id,
            state.seed_mal_id,
            f"error:{state.consecutive_error_count}",
            minimum_minutes,
            max_minutes,
        )

    def _spread_delta(self, user_id, key, purpose, hours):
        minutes = max(1, int(hours * 60))
        return timedelta(
            minutes=self._hash_int(user_id, key, purpose) % minutes
        )

    def _spread_minutes(self, user_id, key, purpose, min_minutes, max_minutes):
        span = max_minutes - min_minutes + 1
        return timedelta(
            minutes=min_minutes + (self._hash_int(user_id, key, purpose) % span)
        )

    def _spread_signed_minutes(self, user_id, key, purpose, max_abs_minutes):
        if max_abs_minutes <= 0:
            return timedelta(0)
        span = (max_abs_minutes * 2) + 1
        offset = (self._hash_int(user_id, key, purpose) % span) - max_abs_minutes
        return timedelta(minutes=offset)

    @staticmethod
    def _clamp_datetime(value, *, minimum, maximum):
        return max(minimum, min(value, maximum))

    def _log_success_cadence(self, state, *, result, window):
        summary = getattr(result, "activity_summary", None)
        logger.info(
            "MAL anime franchise maintenance success cadence",
            extra={
                "user_id": state.user_id,
                "seed_mal_id": state.seed_mal_id,
                "component_root_mal_id": state.component_root_mal_id,
                "cadence_profile": window.profile,
                "cadence_reason": window.reason,
                "window_min_minutes": window.min_minutes,
                "window_max_minutes": window.max_minutes,
                "micro_jitter_minutes": window.micro_jitter_minutes,
                "consecutive_stable_scans": state.consecutive_stable_scans,
                "newest_end_date": getattr(summary, "newest_end_date", None),
                "newest_start_date": getattr(summary, "newest_start_date", None),
                "next_scan_at": state.next_scan_at,
            },
        )

    def _hash_int(self, user_id, key, purpose):
        digest = hashlib.sha256(f"{user_id}:{key}:{purpose}".encode()).hexdigest()
        return int(digest[:12], 16)
