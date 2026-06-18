"""Opportunistic MAL anime franchise discovery persistence and notifications."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from app.models import (
    AnimeFranchiseDiscoveredEntry,
    AnimeFranchiseDiscoveryState,
)
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline
from app.services.anime_tracking import bulk_mal_anime_tracked_ids
from events.notifications import notify_franchise_discovery_after_commit

logger = logging.getLogger(__name__)

NOTIFIABLE_SECTION_KEYS = {
    "series_line",
    "continuity_extras",
    "specials",
    "alternatives",
    "spin_offs",
}
EXCLUDED_SECTION_KEYS = {"related_series", "ignored"}
EXCLUDED_ANIME_MEDIA_TYPES = {"cm", "pv"}


DISCOVERY_NOTIFICATION_RETRY_AFTER = timedelta(hours=6)
DISCOVERY_NOTIFICATION_REACTIVATION_WINDOW = timedelta(days=180)
DISCOVERY_PROCESS_LOCK_TTL_SECONDS = 10 * 60
TEMPORARY_SUPPRESSION_REASONS = {"notifications_disabled"}

SECTION_PRIORITY = {
    "series_line": 100,
    "continuity_extras": 90,
    "specials": 80,
    "alternatives": 70,
    "spin_offs": 60,
}


@dataclass(frozen=True)
class FranchiseDiscoveryCandidate:
    """Normalized MAL anime franchise discovery candidate."""

    media_id: str
    title: str
    section_key: str
    section_label: str = ""
    relation_type: str = ""
    source_media_id: str = ""
    anime_media_type: str = ""
    root_title: str = ""


@dataclass
class AnimeFranchiseDiscoveryStats:
    """Counters emitted while processing franchise discovery candidates."""

    processed_roots: int = 0
    visible_candidates: int = 0
    discoveries_created: int = 0
    discoveries_updated: int = 0
    discoveries_seen: int = 0
    baseline_created: int = 0
    notifications_queued: int = 0
    notifications_suppressed: int = 0
    suppressed_baseline: int = 0
    suppressed_imported_in_same_run: int = 0
    suppressed_already_tracked: int = 0
    suppressed_notifications_disabled: int = 0
    reactivation_window_expired: int = 0
    skipped_not_notifiable_section: int = 0
    skipped_excluded_format: int = 0
    skipped_invalid_media_id: int = 0
    discovery_lock_skipped: int = 0


class AnimeFranchiseDiscoveryProjection:
    """Project a clean franchise UI payload into discovery candidates."""

    def __init__(self, *, ui_pipeline: AnimeFranchiseUiPipeline | None = None):
        """Initialize the projection with an optional UI pipeline."""
        self.ui_pipeline = ui_pipeline or AnimeFranchiseUiPipeline()

    def project(self, snapshot) -> list[FranchiseDiscoveryCandidate]:
        """Return priority-deduplicated discovery candidates for a snapshot."""
        payload = self.ui_pipeline.run(snapshot)
        root_title = payload.display_title
        candidates: list[FranchiseDiscoveryCandidate] = [
            self._candidate(entry, "series_line", "Series", root_title)
            for entry in payload.series.get("entries", [])
        ]
        for section in payload.sections:
            key = str(section.get("key") or "")
            label = str(section.get("title") or key)
            candidates.extend(
                self._candidate(entry, key, label, root_title)
                for entry in section.get("entries", [])
            )

        return self._dedupe_by_section_priority(candidates)

    def _dedupe_by_section_priority(
        self, candidates: list[FranchiseDiscoveryCandidate]
    ) -> list[FranchiseDiscoveryCandidate]:
        invalid_candidates: list[FranchiseDiscoveryCandidate] = []
        deduped: dict[str, FranchiseDiscoveryCandidate] = {}
        for candidate in candidates:
            if not candidate.media_id:
                invalid_candidates.append(candidate)
                continue
            existing = deduped.get(candidate.media_id)
            if existing is None or self._candidate_priority(
                candidate
            ) > self._candidate_priority(existing):
                deduped[candidate.media_id] = candidate
        return [*invalid_candidates, *deduped.values()]

    def _candidate_priority(
        self, candidate: FranchiseDiscoveryCandidate
    ) -> tuple[int, int]:
        eligible_format = int(
            bool(candidate.media_id)
            and candidate.anime_media_type.lower() not in EXCLUDED_ANIME_MEDIA_TYPES
        )
        section_priority = SECTION_PRIORITY.get(candidate.section_key.lower(), 0)
        return (eligible_format, section_priority)

    def _candidate(self, entry, section_key, section_label, root_title):
        """Build one normalized candidate from a UI entry."""
        return FranchiseDiscoveryCandidate(
            media_id=str(entry.get("media_id") or ""),
            title=str(entry.get("title") or ""),
            section_key=str(section_key or "").lower(),
            section_label=str(section_label or ""),
            relation_type=str(entry.get("relation_type") or ""),
            source_media_id=str(entry.get("relation_source_media_id") or ""),
            anime_media_type=str(entry.get("anime_media_type") or "").lower(),
            root_title=str(root_title or ""),
        )


class AnimeFranchiseDiscoveryService:
    """Persist and notify newly visible MAL anime franchise entries."""

    def __init__(self, *, projection: AnimeFranchiseDiscoveryProjection | None = None):
        """Initialize the service with an optional projection."""
        self.projection = projection or AnimeFranchiseDiscoveryProjection()

    def process_snapshot(
        self,
        *,
        user,
        snapshot,
        component_root_mal_id,
        profile_key=None,
        imported_media_ids=None,
        dry_run=False,
        force_baseline_suppression=False,
    ) -> AnimeFranchiseDiscoveryStats:
        """Process one already-built franchise snapshot for one user/root."""
        if dry_run:
            return self._process_snapshot_unlocked(
                user=user,
                snapshot=snapshot,
                component_root_mal_id=component_root_mal_id,
                profile_key=profile_key,
                imported_media_ids=imported_media_ids,
                dry_run=True,
                force_baseline_suppression=force_baseline_suppression,
            )

        lock_key = f"anime-franchise-discovery:{user.id}:{component_root_mal_id}"
        if not cache.add(lock_key, "1", timeout=DISCOVERY_PROCESS_LOCK_TTL_SECONDS):
            logger.info(
                "Skipped MAL anime franchise discovery because processing is locked",
                extra={
                    "user_id": user.id,
                    "component_root_mal_id": str(component_root_mal_id),
                },
            )
            return AnimeFranchiseDiscoveryStats(
                processed_roots=1,
                discovery_lock_skipped=1,
            )

        try:
            return self._process_snapshot_unlocked(
                user=user,
                snapshot=snapshot,
                component_root_mal_id=component_root_mal_id,
                profile_key=profile_key,
                imported_media_ids=imported_media_ids,
                dry_run=False,
                force_baseline_suppression=force_baseline_suppression,
            )
        finally:
            cache.delete(lock_key)

    def _process_snapshot_unlocked(
        self,
        *,
        user,
        snapshot,
        component_root_mal_id,
        profile_key=None,
        imported_media_ids=None,
        dry_run=False,
        force_baseline_suppression=False,
    ) -> AnimeFranchiseDiscoveryStats:
        """Process one already-built franchise snapshot for one user/root."""
        stats = AnimeFranchiseDiscoveryStats(processed_roots=1)
        _ = profile_key
        imported_media_ids = {
            str(media_id).strip()
            for media_id in (imported_media_ids or set())
            if media_id is not None and str(media_id).strip()
        }
        candidates = self.projection.project(snapshot)
        visible = self._filter_visible(candidates, stats)
        stats.visible_candidates = len(visible)
        fingerprint = self.build_fingerprint(visible)
        now = timezone.now()

        state = AnimeFranchiseDiscoveryState.objects.filter(
            user=user,
            component_root_mal_id=str(component_root_mal_id),
        ).first()
        baseline_before_scan = bool(state and state.baseline_completed_at)
        known_discoveries_by_media_id = {}
        if state:
            known_discoveries_by_media_id = {
                discovery.discovered_media_id: discovery
                for discovery in AnimeFranchiseDiscoveredEntry.objects.filter(
                    user=user,
                    component_root_mal_id=str(component_root_mal_id),
                )
            }
        known_ids = set(known_discoveries_by_media_id)
        tracked_ids = self._tracked_media_ids(user, [c.media_id for c in visible])

        if dry_run:
            if not baseline_before_scan:
                stats.baseline_created = 1
            for candidate in visible:
                self._accumulate_dry_run_stats(
                    candidate,
                    stats,
                    baseline_before_scan,
                    known_ids,
                    known_discoveries_by_media_id,
                    tracked_ids,
                    imported_media_ids,
                    user,
                    now=now,
                    force_baseline_suppression=force_baseline_suppression,
                )
            return stats

        with transaction.atomic():
            state, created_state = AnimeFranchiseDiscoveryState.objects.get_or_create(
                user=user,
                component_root_mal_id=str(component_root_mal_id),
                defaults={"first_scanned_at": now},
            )
            baseline_before_scan = bool(state.baseline_completed_at)
            if not baseline_before_scan:
                stats.baseline_created = (
                    1 if created_state or not state.baseline_completed_at else 0
                )
                state.baseline_completed_at = now
            if not state.first_scanned_at:
                state.first_scanned_at = now
            state.last_scanned_at = now
            state.last_fingerprint = fingerprint
            state.last_seen_count = len(visible)
            state.last_error = ""
            state.last_error_at = None
            state.save()

            for candidate in visible:
                self._persist_candidate(
                    user=user,
                    component_root_mal_id=str(component_root_mal_id),
                    candidate=candidate,
                    baseline_before_scan=baseline_before_scan,
                    imported_media_ids=imported_media_ids,
                    tracked_ids=tracked_ids,
                    stats=stats,
                    now=now,
                    force_baseline_suppression=force_baseline_suppression,
                )
        return stats

    def _filter_visible(self, candidates, stats):
        visible = []
        for candidate in candidates:
            if not candidate.media_id:
                stats.skipped_invalid_media_id += 1
                continue
            if candidate.anime_media_type.lower() in EXCLUDED_ANIME_MEDIA_TYPES:
                stats.skipped_excluded_format += 1
                continue
            section_key = candidate.section_key.lower()
            if section_key in EXCLUDED_SECTION_KEYS:
                stats.skipped_not_notifiable_section += 1
                continue
            if section_key not in NOTIFIABLE_SECTION_KEYS:
                stats.skipped_not_notifiable_section += 1
                continue
            visible_candidate = candidate
            if section_key != candidate.section_key:
                visible_candidate = replace(candidate, section_key=section_key)
            visible.append(visible_candidate)
        return visible

    @staticmethod
    def build_fingerprint(candidates):
        """Build a stable hash from visible normalized candidates."""
        payload = sorted(
            (
                {
                    "media_id": c.media_id,
                    "section_key": c.section_key.lower(),
                    "relation_type": c.relation_type,
                    "anime_media_type": c.anime_media_type.lower(),
                }
                for c in candidates
            ),
            key=lambda item: item["media_id"],
        )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def record_error(self, *, user, component_root_mal_id, error) -> None:
        """Persist best-effort discovery error details for a user/root."""
        now = timezone.now()
        state, _created = AnimeFranchiseDiscoveryState.objects.get_or_create(
            user=user,
            component_root_mal_id=str(component_root_mal_id),
            defaults={"first_scanned_at": now},
        )
        if not state.first_scanned_at:
            state.first_scanned_at = now
        state.last_scanned_at = now
        state.last_error = str(error)
        state.last_error_at = now
        state.save(
            update_fields=[
                "first_scanned_at",
                "last_scanned_at",
                "last_error",
                "last_error_at",
            ]
        )

    def _tracked_media_ids(self, user, media_ids):
        return bulk_mal_anime_tracked_ids(user_id=user.id, media_ids=media_ids)

    def _suppression_reason(
        self,
        candidate,
        baseline,
        imported_media_ids,
        tracked_ids,
        user,
        *,
        force_baseline_suppression=False,
    ):
        """Return the main reason a candidate should not notify."""
        if force_baseline_suppression or not baseline:
            return "baseline"
        if candidate.media_id in imported_media_ids:
            return "imported_in_same_run"
        if candidate.media_id in tracked_ids:
            return "already_tracked"
        if (
            not user.franchise_discovery_notifications_enabled
            or not user.notification_urls.strip()
        ):
            return "notifications_disabled"
        return ""

    def _count_suppression(self, reason, stats):
        """Increment aggregate counters for one suppression reason."""
        if not reason:
            return
        stats.notifications_suppressed += 1
        field = f"suppressed_{reason}"
        if hasattr(stats, field):
            setattr(stats, field, getattr(stats, field) + 1)

    def _persist_candidate(
        self,
        *,
        user,
        component_root_mal_id,
        candidate,
        baseline_before_scan,
        imported_media_ids,
        tracked_ids,
        stats,
        now,
        force_baseline_suppression=False,
    ):
        reason = self._suppression_reason(
            candidate,
            baseline_before_scan,
            imported_media_ids,
            tracked_ids,
            user,
            force_baseline_suppression=force_baseline_suppression,
        )
        persistent_reason = self._persistent_suppression_reason(reason)
        defaults = {
            "title": candidate.title,
            "section_key": candidate.section_key,
            "section_label": candidate.section_label,
            "relation_type": candidate.relation_type,
            "source_media_id": candidate.source_media_id,
            "anime_media_type": candidate.anime_media_type,
            "root_title": candidate.root_title,
            "notification_suppressed_reason": persistent_reason,
        }
        discovery, created = (
            AnimeFranchiseDiscoveredEntry.objects.select_for_update().get_or_create(
                user=user,
                component_root_mal_id=component_root_mal_id,
                discovered_media_id=candidate.media_id,
                defaults=defaults,
            )
        )
        if not created:
            update_fields = []
            for field, value in defaults.items():
                if field == "notification_suppressed_reason":
                    continue
                if getattr(discovery, field) != value:
                    setattr(discovery, field, value)
                    update_fields.append(field)
            if (
                not discovery.notified_at
                and discovery.notification_suppressed_reason
                in TEMPORARY_SUPPRESSION_REASONS
            ):
                discovery.notification_suppressed_reason = ""
                update_fields.append("notification_suppressed_reason")
            if (
                not discovery.notified_at
                and not discovery.notification_suppressed_reason
                and persistent_reason
            ):
                discovery.notification_suppressed_reason = persistent_reason
                update_fields.append("notification_suppressed_reason")
            discovery.last_seen_at = now
            update_fields.append("last_seen_at")
            discovery.save(update_fields=update_fields)
        stats.discoveries_seen += 1
        if created:
            stats.discoveries_created += 1
        else:
            stats.discoveries_updated += 1
        self._count_suppression(reason, stats)
        if self._should_queue_notification(
            discovery=discovery,
            reason=reason,
            now=now,
        ):
            # This timestamp means a notification queue attempt was requested.
            # The actual Celery enqueue happens in the on_commit callback.
            # notified_at remains the durable marker for a successful send.
            discovery.notification_queued_at = now
            discovery.last_seen_at = now
            discovery.save(update_fields=["notification_queued_at", "last_seen_at"])
            notify_franchise_discovery_after_commit(user.id, discovery.id)
            stats.notifications_queued += 1
        elif (
            self._queue_block_reason(
                discovery=discovery,
                reason=reason,
                now=now,
            )
            == "reactivation_window_expired"
        ):
            stats.reactivation_window_expired += 1

    def _persistent_suppression_reason(self, reason: str) -> str:
        """Return the durable suppression reason to persist for a scan result.

        Baseline, imported-in-same-run, and already-tracked are permanent
        suppressions. When franchise discovery notifications are disabled,
        discoveries are still persisted but no notification is queued. If the
        user later re-enables notifications, still-visible unnotified discoveries
        become eligible again during the next normal franchise scan, subject to
        the reactivation window. No notification is sent immediately when the
        user toggles the setting back on; discovery remains opportunistic.
        """
        if reason in TEMPORARY_SUPPRESSION_REASONS:
            return ""
        return reason

    def _reactivation_window_expired(self, *, discovery, now) -> bool:
        """Return whether an unnotified discovery is too old to reactivate."""
        return (
            discovery.first_seen_at
            < now - DISCOVERY_NOTIFICATION_REACTIVATION_WINDOW
        )

    def _queue_block_reason(self, *, discovery, reason: str, now) -> str:
        """Return the reason a discovery cannot currently queue."""
        if reason:
            return reason
        if discovery.notified_at:
            return "notified"
        if (
            discovery.notification_suppressed_reason
            and discovery.notification_suppressed_reason
            not in TEMPORARY_SUPPRESSION_REASONS
        ):
            return "persistent_suppression"
        if self._reactivation_window_expired(discovery=discovery, now=now):
            return "reactivation_window_expired"
        if (
            discovery.notification_queued_at
            and discovery.notification_queued_at
            > now - DISCOVERY_NOTIFICATION_RETRY_AFTER
        ):
            return "retry_cooldown"
        return ""

    def _should_queue_notification(self, *, discovery, reason: str, now) -> bool:
        """Return whether a discovery should queue or retry notification."""
        return not self._queue_block_reason(
            discovery=discovery,
            reason=reason,
            now=now,
        )

    def _accumulate_dry_run_stats(
        self,
        candidate,
        stats,
        baseline,
        known_ids,
        known_discoveries_by_media_id,
        tracked_ids,
        imported_media_ids,
        user,
        *,
        now,
        force_baseline_suppression=False,
    ):
        stats.discoveries_seen += 1
        if candidate.media_id in known_ids:
            stats.discoveries_updated += 1
        else:
            stats.discoveries_created += 1
        reason = self._suppression_reason(
            candidate,
            baseline,
            imported_media_ids,
            tracked_ids,
            user,
            force_baseline_suppression=force_baseline_suppression,
        )
        self._count_suppression(reason, stats)
        if reason:
            return
        existing_discovery = known_discoveries_by_media_id.get(candidate.media_id)
        if existing_discovery:
            if self._should_queue_notification(
                discovery=existing_discovery,
                reason=reason,
                now=now,
            ):
                stats.notifications_queued += 1
            elif (
                self._queue_block_reason(
                    discovery=existing_discovery,
                    reason=reason,
                    now=now,
                )
                == "reactivation_window_expired"
            ):
                stats.reactivation_window_expired += 1
        else:
            stats.notifications_queued += 1
