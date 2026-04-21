"""Persistent incremental scheduling for franchise imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from app.models import Anime, AnimeImportScanState, MediaTypes, Sources, Status
from app.services.anime_franchise_import_profiles import BaseImportProfile


@dataclass(frozen=True)
class DueSeed:
    user_id: int
    seed_mal_id: str


class AnimeImportStateService:
    """Select due seeds and maintain profile-aware scan state."""

    eligible_statuses = [Status.PLANNING.value, Status.IN_PROGRESS.value, Status.COMPLETED.value]
    DEFAULT_JITTER_WINDOW_MINUTES = 30
    LONG_STABLE_JITTER_RATIO = 0.10
    LONG_STABLE_JITTER_MAX_MINUTES = 24 * 60
    LONG_STABLE_JITTER_THRESHOLD_HOURS = 48

    def build_fingerprint(self, profile_key: str, payload: dict) -> str:
        data = {"profile": profile_key, "payload": payload}
        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def select_due_seeds(
        self,
        *,
        profile: BaseImportProfile,
        profile_key: str,
        user_ids: list[int] | None = None,
        full_rescan: bool = False,
        limit: int | None = None,
    ) -> tuple[list[DueSeed], int]:
        query = Anime.objects.filter(
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
            status__in=self.eligible_statuses,
        ).select_related("item")
        if user_ids:
            query = query.filter(user_id__in=user_ids)

        seed_rows = (
            query.values_list("user_id", "item__media_id")
            .order_by("user_id", "item__media_id")
            .distinct()
        )
        seeds: list[DueSeed] = []
        skipped_not_due = 0
        now = timezone.now()
        for user_id, seed_mal_id in seed_rows:
            seed = DueSeed(user_id=user_id, seed_mal_id=seed_mal_id)
            known_canonical_root = self._known_component_root_media_id(
                user_id=user_id,
                seed_mal_id=seed.seed_mal_id,
            )
            if not profile.is_seed_eligible(
                seed_mal_id=seed.seed_mal_id,
                known_canonical_root=known_canonical_root,
            ):
                continue
            if full_rescan:
                seeds.append(seed)
                continue

            state = AnimeImportScanState.objects.filter(
                user_id=seed.user_id,
                seed_mal_id=seed.seed_mal_id,
                profile_key=profile_key,
            ).first()
            if state is None or state.next_scan_at <= now:
                seeds.append(seed)
            else:
                skipped_not_due += 1

        seeds.sort(key=lambda item: (item.user_id, int(item.seed_mal_id)))
        if limit:
            seeds = seeds[:limit]
        return seeds, skipped_not_due

    def _known_component_root_media_id(
        self,
        *,
        user_id: int,
        seed_mal_id: str,
    ) -> str | None:
        """Return known canonical continuity root for the seed's component.

        This value comes from ``AnimeImportScanState.component_root_mal_id`` and
        is treated as a global continuity-component root, not a profile-specific root.

        Invariant: ``component_root_mal_id`` represents the same canonical root for
        the continuity component regardless of which profile row recorded it.
        """
        prioritized_state = (
            AnimeImportScanState.objects.filter(
                user_id=user_id,
                seed_mal_id=seed_mal_id,
            )
            .exclude(component_root_mal_id="")
            .order_by("-last_success_at", "profile_key")
            .first()
        )
        if prioritized_state is None:
            return None
        return prioritized_state.component_root_mal_id

    def record_success(
        self,
        *,
        user_id: int,
        seed_mal_id: str,
        profile_key: str,
        fingerprint: str,
        component_root_mal_id: str,
        component_size: int,
    ) -> tuple[AnimeImportScanState, bool, bool]:
        now = timezone.now()
        state, created = AnimeImportScanState.objects.get_or_create(
            user_id=user_id,
            seed_mal_id=seed_mal_id,
            profile_key=profile_key,
            defaults={"next_scan_at": now},
        )
        changed_result = state.last_result_fingerprint != fingerprint

        state.last_scanned_at = now
        state.last_success_at = now
        state.last_result_fingerprint = fingerprint
        state.consecutive_error_count = 0
        state.component_root_mal_id = component_root_mal_id
        state.last_component_size = component_size

        if changed_result:
            state.last_change_at = now
            state.consecutive_stable_scans = 0
            delay = self._stable_delay(
                hours=6,
                stable_count=0,
                user_id=user_id,
                seed_mal_id=seed_mal_id,
                profile_key=profile_key,
            )
        else:
            state.consecutive_stable_scans += 1
            delay = self._stable_delay(
                hours=12,
                stable_count=state.consecutive_stable_scans,
                user_id=user_id,
                seed_mal_id=seed_mal_id,
                profile_key=profile_key,
            )

        state.next_scan_at = now + delay
        state.save()
        return state, created, changed_result

    def record_error(self, *, user_id: int, seed_mal_id: str, profile_key: str) -> tuple[AnimeImportScanState, bool]:
        now = timezone.now()
        state, created = AnimeImportScanState.objects.get_or_create(
            user_id=user_id,
            seed_mal_id=seed_mal_id,
            profile_key=profile_key,
            defaults={"next_scan_at": now},
        )
        state.last_scanned_at = now
        state.last_error_at = now
        state.consecutive_error_count += 1
        base = min(2 ** state.consecutive_error_count, 24)
        state.next_scan_at = now + self._jittered_delay(
            hours=base,
            user_id=user_id,
            seed_mal_id=seed_mal_id,
            profile_key=profile_key,
        )
        state.save()
        return state, created

    def mark_due_now(self, *, user_id: int, seed_mal_id: str, profiles: list[str] | None = None) -> int:
        now = timezone.now()
        target_profiles = profiles or ["continuity", "satellites", "complete"]
        changed_rows = 0
        for profile_key in target_profiles:
            state, created = AnimeImportScanState.objects.get_or_create(
                user_id=user_id,
                seed_mal_id=seed_mal_id,
                profile_key=profile_key,
                defaults={"next_scan_at": now},
            )
            if created:
                changed_rows += 1
                continue

            if state.next_scan_at != now:
                state.next_scan_at = now
                state.save(update_fields=["next_scan_at", "updated_at"])
            changed_rows += 1
        return changed_rows

    def _stable_delay(
        self,
        *,
        hours: int,
        stable_count: int,
        user_id: int,
        seed_mal_id: str,
        profile_key: str,
    ) -> timedelta:
        base_hours = min(hours * (2 ** min(stable_count, 4)), 24 * 14)
        jitter_window_minutes = self._stable_jitter_window_minutes(base_hours)
        return self._jittered_delay(
            hours=base_hours,
            user_id=user_id,
            seed_mal_id=seed_mal_id,
            profile_key=profile_key,
            jitter_window_minutes=jitter_window_minutes,
        )

    def _stable_jitter_window_minutes(self, base_hours: int) -> int:
        if base_hours < self.LONG_STABLE_JITTER_THRESHOLD_HOURS:
            return self.DEFAULT_JITTER_WINDOW_MINUTES

        proportional_minutes = int(base_hours * 60 * self.LONG_STABLE_JITTER_RATIO)
        return min(
            max(proportional_minutes, self.DEFAULT_JITTER_WINDOW_MINUTES),
            self.LONG_STABLE_JITTER_MAX_MINUTES,
        )

    def _jittered_delay(
        self,
        *,
        hours: int,
        user_id: int,
        seed_mal_id: str,
        profile_key: str,
        jitter_window_minutes: int = DEFAULT_JITTER_WINDOW_MINUTES,
    ) -> timedelta:
        seed = f"{user_id}:{seed_mal_id}:{profile_key}:{hours}"
        digest = hashlib.md5(seed.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324
        jitter_minutes = int(digest[:8], 16) % (jitter_window_minutes + 1)
        return timedelta(hours=hours, minutes=jitter_minutes)
