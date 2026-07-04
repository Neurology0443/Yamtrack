"""Persistent scheduler for autonomous MAL anime franchise maintenance."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
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

BRANCH_ROOT_SEED_ID_STATS_LIMIT = 25

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
    branch_root_coverage_skipped: int = 0
    branch_root_state_coverage_skipped: int = 0
    branch_root_duplicate_coverage_bypassed: int = 0
    branch_root_duplicate_root_bypassed: int = 0
    branch_root_preserved_seed_ids: list[str] = field(default_factory=list)

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

    def scan_due(self, *, limit=None) -> AnimeFranchiseMaintenanceScanStats:  # noqa: C901, PLR0912, PLR0915
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
        branch_root_candidate_seed_ids_by_user = (
            self._branch_root_candidate_seed_ids_by_user(
                user_ids={state.user_id for state in states},
            )
        )

        for state in states:
            seed_key = (state.user_id, state.seed_mal_id)
            if seed_key in covered_seed_keys:
                covered_result = covered_results_by_seed.get(seed_key)
                covered_root_id = (
                    getattr(covered_result, "component_root_mal_id", "")
                    if covered_result is not None
                    else state.component_root_mal_id
                )
                if self._is_branch_root_candidate(
                    user_id=state.user_id,
                    seed_mal_id=state.seed_mal_id,
                    current_component_root_mal_id=covered_root_id,
                    branch_root_candidate_seed_ids_by_user=(
                        branch_root_candidate_seed_ids_by_user
                    ),
                ):
                    stats.branch_root_duplicate_coverage_bypassed += 1
                    self._record_branch_root_preserved_seed(stats, state.seed_mal_id)
                else:
                    stats.skipped_duplicate_root += 1
                    self._mark_duplicate_covered(
                        state,
                        now=now,
                        result=covered_result,
                    )
                    continue
            if not self._is_seed_tracked(state):
                stats.skipped_not_tracked += 1
                self._push_state_forward(state, now=now)
                continue
            if state.component_root_mal_id:
                root_key = (state.user_id, state.component_root_mal_id)
                if root_key in processed_roots_by_user:
                    if self._is_branch_root_candidate(
                        user_id=state.user_id,
                        seed_mal_id=state.seed_mal_id,
                        current_component_root_mal_id=state.component_root_mal_id,
                        branch_root_candidate_seed_ids_by_user=(
                            branch_root_candidate_seed_ids_by_user
                        ),
                    ):
                        stats.branch_root_duplicate_root_bypassed += 1
                        self._record_branch_root_preserved_seed(
                            stats, state.seed_mal_id
                        )
                    else:
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
            for raw_media_id in result.tracked_member_media_ids:
                media_id = str(raw_media_id)
                member_seed_key = (state.user_id, media_id)
                if media_id != str(
                    state.seed_mal_id
                ) and self._is_branch_root_candidate(
                    user_id=state.user_id,
                    seed_mal_id=media_id,
                    current_component_root_mal_id=result.component_root_mal_id,
                    branch_root_candidate_seed_ids_by_user=(
                        branch_root_candidate_seed_ids_by_user
                    ),
                ):
                    stats.branch_root_coverage_skipped += 1
                    self._record_branch_root_preserved_seed(stats, media_id)
                    continue
                covered_seed_keys.add(member_seed_key)
                covered_results_by_seed[member_seed_key] = result
            if result.component_root_mal_id:
                root_key = (state.user_id, result.component_root_mal_id)
                processed_roots_by_user.add(root_key)
                processed_results_by_root[root_key] = result
            self._cover_tracked_member_states(
                state,
                result=result,
                now=now,
                branch_root_candidate_seed_ids_by_user=(
                    branch_root_candidate_seed_ids_by_user
                ),
                stats=stats,
            )
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
        if changed or root_changed:
            window = ScanWindow(
                profile="HOT",
                reason="covered_state_changed",
                min_minutes=6 * 60,
                max_minutes=36 * 60,
                micro_jitter_minutes=15,
            )
        else:
            window = compute_success_scan_window(
                activity_summary=result.activity_summary,
                state=state,
                result=result,
                now=now,
            )
        state.next_scan_at = self._next_success_scan_at(
            state, result=result, window=window, now=now
        )
        state.save()
        self._log_success_cadence(state, result=result, window=window)

    def _push_state_forward(self, state, *, now):
        # Non-tracked states are not actionable until the user tracks the seed again.
        # Keep them on a slow sweep to avoid repeatedly scanning seeds that are no
        # longer in eligible user lists. Do not use the legacy stable backoff here.
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

    def _branch_root_candidate_seed_ids_by_user(  # noqa: C901, PLR0912
        self, *, user_ids
    ) -> dict[int, set[str]]:
        user_ids = {user_id for user_id in user_ids if user_id is not None}
        if not user_ids:
            return {}

        eligible_seed_ids_by_user = defaultdict(set)
        eligible_rows = (
            self._eligible_anime_queryset()
            .filter(user_id__in=user_ids)
            .values_list("user_id", "item__media_id")
        )
        for user_id, raw_media_id in eligible_rows:
            media_id = str(raw_media_id or "").strip()
            if media_id:
                eligible_seed_ids_by_user[user_id].add(media_id)

        if not eligible_seed_ids_by_user:
            return {}

        rows = AnimeFranchiseMaintenanceScanState.objects.filter(
            user_id__in=user_ids
        ).values_list("user_id", "seed_mal_id", "component_root_mal_id")
        seed_ids_by_user = defaultdict(set)
        root_children_by_user = defaultdict(lambda: defaultdict(set))
        for user_id, raw_seed_mal_id, raw_component_root_mal_id in rows:
            seed_id = str(raw_seed_mal_id or "").strip()
            root_id = str(raw_component_root_mal_id or "").strip()
            eligible_seed_ids = eligible_seed_ids_by_user.get(user_id, set())
            if not seed_id:
                continue
            if seed_id not in eligible_seed_ids:
                continue
            seed_ids_by_user[user_id].add(seed_id)
            if root_id:
                root_children_by_user[user_id][root_id].add(seed_id)

        candidate_ids_by_user = defaultdict(set)
        for user_id, seed_ids in seed_ids_by_user.items():
            eligible_seed_ids = eligible_seed_ids_by_user.get(user_id, set())
            for root_id, child_seed_ids in root_children_by_user[user_id].items():
                if root_id not in seed_ids:
                    continue
                if root_id not in eligible_seed_ids:
                    continue
                if not any(
                    child_seed_id != root_id for child_seed_id in child_seed_ids
                ):
                    continue
                candidate_ids_by_user[user_id].add(root_id)
        return {
            user_id: set(candidate_ids)
            for user_id, candidate_ids in candidate_ids_by_user.items()
        }

    def _is_branch_root_candidate(
        self,
        *,
        user_id,
        seed_mal_id,
        current_component_root_mal_id,
        branch_root_candidate_seed_ids_by_user,
    ) -> bool:
        seed_id = str(seed_mal_id or "").strip()
        current_root_id = str(current_component_root_mal_id or "").strip()
        if not seed_id:
            return False
        if seed_id == current_root_id:
            return False
        return seed_id in branch_root_candidate_seed_ids_by_user.get(user_id, set())

    def _record_branch_root_preserved_seed(self, stats, seed_mal_id):
        seed_id = str(seed_mal_id or "").strip()
        if not seed_id:
            return
        if seed_id in stats.branch_root_preserved_seed_ids:
            return
        if len(stats.branch_root_preserved_seed_ids) >= BRANCH_ROOT_SEED_ID_STATS_LIMIT:
            return
        stats.branch_root_preserved_seed_ids.append(seed_id)

    def _cover_tracked_member_states(
        self,
        state,
        *,
        result,
        now,
        branch_root_candidate_seed_ids_by_user=None,
        stats=None,
    ):
        tracked_ids = self._tracked_seed_ids_for_user(
            user_id=state.user_id,
            media_ids=result.tracked_member_media_ids,
        )
        current_seed_mal_id = str(state.seed_mal_id)
        for raw_media_id in tracked_ids:
            media_id = str(raw_media_id)
            if media_id == current_seed_mal_id:
                continue
            if self._is_branch_root_candidate(
                user_id=state.user_id,
                seed_mal_id=media_id,
                current_component_root_mal_id=result.component_root_mal_id,
                branch_root_candidate_seed_ids_by_user=(
                    branch_root_candidate_seed_ids_by_user or {}
                ),
            ):
                if stats is not None:
                    stats.branch_root_state_coverage_skipped += 1
                    self._record_branch_root_preserved_seed(stats, media_id)
                continue
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
            if member_state.pk == state.pk:
                continue
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
        return timedelta(minutes=self._hash_int(user_id, key, purpose) % minutes)

    def _spread_minutes(self, user_id, key, purpose, min_minutes, max_minutes):
        max_minutes = max(max_minutes, min_minutes)
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
