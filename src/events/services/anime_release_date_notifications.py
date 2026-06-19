"""MAL anime start-date scanning and notification service."""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import mal, mal_cache
from events.models import (
    AnimeReleaseDateNotificationDelivery,
    AnimeReleaseDateScanState,
    AnimeStartDatePrecision,
)
from events.notifications import send_user_notification

logger = logging.getLogger(__name__)

YEAR_RE = re.compile(r"^\d{4}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ACTIVE_ANIME_STATUSES = (Status.PLANNING.value, Status.IN_PROGRESS.value)
LONG_BACKOFF_STABLE_SCANS = 6
MEDIUM_BACKOFF_STABLE_SCANS = 3


@dataclass(frozen=True)
class ParsedAnimeStartDate:
    """Strictly parsed MAL anime start date."""

    raw: str
    normalized: str
    precision: str
    date_value: date | None
    sort_year: int
    sort_month: int | None
    sort_day: int | None


@dataclass
class AnimeReleaseDateScanStats:
    """JSON-serializable counters for one scan or metadata observation."""

    scanned: int = 0
    states_created: int = 0
    initialized: int = 0
    announced: int = 0
    updated: int = 0
    notifications_sent: int = 0
    notifications_failed: int = 0
    errors: int = 0
    skipped: int = 0

    def merge(self, other: AnimeReleaseDateScanStats) -> None:
        """Merge another result into this one."""
        for field_name in self.__dataclass_fields__:
            setattr(
                self,
                field_name,
                getattr(self, field_name) + getattr(other, field_name),
            )

    def as_dict(self) -> dict[str, int]:
        """Return counters as a plain dictionary."""
        return asdict(self)


def parse_mal_start_date(value) -> ParsedAnimeStartDate | None:  # noqa: PLR0911
    """Parse supported MAL date precision without accepting loose ISO forms."""
    if not isinstance(value, str) or not value:
        return None

    if YEAR_RE.fullmatch(value):
        year = int(value)
        try:
            date(year, 1, 1)
        except ValueError:
            return None
        return ParsedAnimeStartDate(
            raw=value,
            normalized=value,
            precision=AnimeStartDatePrecision.YEAR,
            date_value=None,
            sort_year=year,
            sort_month=None,
            sort_day=None,
        )

    if MONTH_RE.fullmatch(value):
        year, month = (int(part) for part in value.split("-"))
        try:
            date(year, month, 1)
        except ValueError:
            return None
        return ParsedAnimeStartDate(
            raw=value,
            normalized=value,
            precision=AnimeStartDatePrecision.MONTH,
            date_value=None,
            sort_year=year,
            sort_month=month,
            sort_day=None,
        )

    if DAY_RE.fullmatch(value):
        try:
            date_value = date.fromisoformat(value)
        except ValueError:
            return None
        return ParsedAnimeStartDate(
            raw=value,
            normalized=value,
            precision=AnimeStartDatePrecision.DAY,
            date_value=date_value,
            sort_year=date_value.year,
            sort_month=date_value.month,
            sort_day=date_value.day,
        )

    return None


def is_mal_cache_recent_for_release_date_scan(
    meta,
    *,
    max_age_hours: int,
) -> bool:
    """Check cache age using the release-date scan's own freshness window."""
    if not meta or not meta.get("fetched_at"):
        return False

    fetched_at = meta["fetched_at"]
    if isinstance(fetched_at, datetime):
        parsed = fetched_at
    elif isinstance(fetched_at, str):
        try:
            parsed = parse_datetime(fetched_at)
        except (TypeError, ValueError):
            return False
    else:
        return False

    if parsed is None:
        return False
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed >= timezone.now() - timedelta(hours=max_age_hours)


class AnimeReleaseDateNotificationService:
    """Own release-date selection, state transitions, and delivery."""

    lock_key = "anime-release-date-scan"

    def scan_due_items(self) -> dict[str, int | str]:
        """Scan a bounded deterministic batch of eligible MAL anime."""
        stats = AnimeReleaseDateScanStats()
        lock_timeout = settings.ANIME_RELEASE_DATE_SCAN_LOCK_MINUTES * 60
        if not cache.add(self.lock_key, "1", timeout=lock_timeout):
            result = stats.as_dict()
            result.update(
                {
                    "skipped": 1,
                    "reason": "already_running",
                },
            )
            return result

        try:
            now = timezone.now()
            logger.info(
                "Anime release date scan started batch_size=%s",
                settings.ANIME_RELEASE_DATE_SCAN_BATCH_SIZE,
            )
            eligible_item_ids = self._eligible_item_ids()
            stats.states_created = self._create_missing_states(
                eligible_item_ids,
                now=now,
            )
            today = timezone.localdate()
            AnimeReleaseDateScanState.objects.filter(
                disabled=False,
                last_seen_start_date__lt=today,
            ).update(disabled=True)
            cutoff = now - timedelta(
                hours=settings.ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS,
            )
            due_states = list(
                AnimeReleaseDateScanState.objects.filter(
                    item_id__in=eligible_item_ids,
                    disabled=False,
                    next_scan_at__lte=now,
                )
                .filter(
                    Q(last_checked_at__isnull=True)
                    | Q(last_checked_at__lte=cutoff),
                )
                .filter(
                    Q(last_seen_start_date__isnull=True)
                    | Q(last_seen_start_date__gte=today),
                )
                .select_related("item")
                .order_by("next_scan_at", "id")[
                    : settings.ANIME_RELEASE_DATE_SCAN_BATCH_SIZE
                ],
            )

            for state in due_states:
                stats.scanned += 1
                try:
                    result = self._process_due_state(state)
                except Exception as error:  # keep the bounded batch moving
                    logger.exception(
                        "Anime release date scan failed item=%s media_id=%s",
                        state.item_id,
                        state.item.media_id,
                    )
                    self._mark_error(state, error)
                    result = AnimeReleaseDateScanStats(errors=1)
                stats.merge(result)

            logger.info(
                "Anime release date scan completed scanned=%s initialized=%s "
                "announced=%s updated=%s sent=%s failed=%s errors=%s",
                stats.scanned,
                stats.initialized,
                stats.announced,
                stats.updated,
                stats.notifications_sent,
                stats.notifications_failed,
                stats.errors,
            )
            return stats.as_dict()
        finally:
            cache.delete(self.lock_key)

    def process_metadata_refresh(
        self,
        *,
        media_id,
        old_metadata,
        new_metadata,
        source: str,
    ) -> dict[str, int]:
        """Observe an existing MAL refresh without making another provider call."""
        item = Item.objects.filter(
            media_id=str(media_id),
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
        ).first()
        if item is None or not self._eligible_users(item):
            return AnimeReleaseDateScanStats(skipped=1).as_dict()

        state = AnimeReleaseDateScanState.objects.filter(item=item).first()
        stats = AnimeReleaseDateScanStats()
        if state is None:
            initial_metadata = (
                old_metadata if old_metadata is not None else new_metadata
            )
            initial = self._process_item_metadata(
                item=item,
                metadata=initial_metadata,
                source=source,
                notify=False,
            )
            stats.merge(initial)
            if old_metadata is None:
                return stats.as_dict()

        stats.merge(
            self._process_item_metadata(
                item=item,
                metadata=new_metadata,
                source=source,
                notify=True,
            ),
        )
        return stats.as_dict()

    def initialize_or_prioritize_imported_item(self, *, item, metadata) -> None:
        """Initialize an imported item silently and make it promptly scannable."""
        if not self._is_mal_anime(item):
            return

        now = timezone.now()
        state, _ = AnimeReleaseDateScanState.objects.get_or_create(
            item=item,
            defaults={"next_scan_at": now},
        )
        if state.initialized_at is None:
            self._process_item_metadata(
                item=item,
                metadata=metadata,
                source="franchise_import",
                notify=False,
                require_eligible_users=False,
            )
            return

        if state.disabled:
            return
        if state.next_scan_at > now:
            state.next_scan_at = now
            state.save(update_fields=["next_scan_at"])

    def _eligible_item_ids(self) -> list[int]:
        candidates = (
            Anime.objects.filter(
                status__in=ACTIVE_ANIME_STATUSES,
                item__source=Sources.MAL.value,
                item__media_type=MediaTypes.ANIME.value,
                user__anime_release_date_notifications_enabled=True,
            )
            .exclude(user__notification_excluded_items__id=F("item_id"))
            .values_list("item_id", "user__notification_urls")
            .distinct()
        )
        return sorted(
            {
                item_id
                for item_id, notification_urls in candidates
                if notification_urls.strip()
            },
        )

    def _eligible_users(self, item) -> list:
        candidates = (
            get_user_model()
            .objects.filter(
                anime__item=item,
                anime__status__in=ACTIVE_ANIME_STATUSES,
                anime_release_date_notifications_enabled=True,
            )
            .exclude(notification_excluded_items=item)
            .distinct()
            .order_by("id")
        )
        return [user for user in candidates if user.notification_urls.strip()]

    def _create_missing_states(self, item_ids: list[int], *, now) -> int:
        existing_ids = set(
            AnimeReleaseDateScanState.objects.filter(
                item_id__in=item_ids,
            ).values_list("item_id", flat=True),
        )
        missing_ids = sorted(set(item_ids) - existing_ids)
        AnimeReleaseDateScanState.objects.bulk_create(
            [
                AnimeReleaseDateScanState(item_id=item_id, next_scan_at=now)
                for item_id in missing_ids
            ],
            ignore_conflicts=True,
        )
        return len(missing_ids)

    def _process_due_state(
        self,
        state: AnimeReleaseDateScanState,
    ) -> AnimeReleaseDateScanStats:
        item = state.item
        users = self._eligible_users(item)
        if not users:
            state.next_scan_at = timezone.now() + timedelta(days=7)
            state.save(update_fields=["next_scan_at"])
            logger.info(
                "Anime release date scan skipped media_id=%s reason=no_eligible_users",
                item.media_id,
            )
            return AnimeReleaseDateScanStats(skipped=1)

        metadata, cache_meta = mal_cache.load_anime_cache(item.media_id)
        if not is_mal_cache_recent_for_release_date_scan(
            cache_meta,
            max_age_hours=settings.ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS,
        ):
            metadata = mal.anime(item.media_id, refresh_cache=True)

        return self._process_item_metadata(
            item=item,
            metadata=metadata,
            source="dedicated_scan",
            notify=True,
            eligible_users=users,
        )

    def _process_item_metadata(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        *,
        item,
        metadata,
        source: str,
        notify: bool,
        require_eligible_users: bool = True,
        eligible_users: list | None = None,
    ) -> AnimeReleaseDateScanStats:
        stats = AnimeReleaseDateScanStats()
        if not self._is_mal_anime(item):
            stats.skipped = 1
            return stats

        users = eligible_users
        if users is None:
            users = self._eligible_users(item)
        if require_eligible_users and not users:
            stats.skipped = 1
            return stats

        details = metadata.get("details", {}) if isinstance(metadata, dict) else {}
        raw_value = details.get("start_date")
        raw_text = raw_value if isinstance(raw_value, str) else ""
        parsed = parse_mal_start_date(raw_value)
        mal_status = str(details.get("status") or "")
        now = timezone.now()

        with transaction.atomic():
            state, created = (
                AnimeReleaseDateScanState.objects.select_for_update().get_or_create(
                    item=item,
                    defaults={"next_scan_at": now},
                )
            )
            if created:
                stats.states_created = 1

            old_text = state.last_seen_start_date_text
            old_precision = state.last_seen_start_date_precision
            state.last_seen_raw_start_date = raw_text[:32]
            state.last_seen_mal_status = mal_status[:64]
            state.last_checked_at = now
            state.last_success_at = now
            state.consecutive_error_count = 0

            if state.initialized_at is None:
                self._store_parsed_date(state, parsed)
                state.initialized_at = now
                state.consecutive_stable_scans = 0
                if parsed and self._is_definitively_past(
                    parsed,
                    timezone.localdate(),
                ):
                    state.disabled = True
                else:
                    self._finish_state_schedule(state, parsed, mal_status, now=now)
                state.save()
                stats.initialized = 1
                logger.info(
                    "Anime release date scan initialized item=%s media_id=%s "
                    "date=%s precision=%s",
                    item.id,
                    item.media_id,
                    parsed.normalized if parsed else None,
                    parsed.precision if parsed else "",
                )
                return stats

            if parsed is None:
                state.consecutive_stable_scans += 1
                self._finish_state_schedule(state, parsed, mal_status, now=now)
                state.save()
                return stats

            if self._is_definitively_past(parsed, timezone.localdate()):
                self._store_parsed_date(state, parsed)
                state.disabled = True
                state.save()
                return stats

            transition = old_text != parsed.normalized
            state.disabled = False
            if transition:
                self._store_parsed_date(state, parsed)
                state.last_change_at = now
                state.consecutive_stable_scans = 0
            else:
                state.consecutive_stable_scans += 1
            self._finish_state_schedule(state, parsed, mal_status, now=now)
            state.save()

        if not transition or not notify:
            return stats

        change_kind = (
            AnimeReleaseDateNotificationDelivery.ChangeKind.ANNOUNCED
            if not old_text
            else AnimeReleaseDateNotificationDelivery.ChangeKind.UPDATED
        )
        if change_kind == AnimeReleaseDateNotificationDelivery.ChangeKind.ANNOUNCED:
            stats.announced = 1
            logger.info(
                "Anime release date scan detected announced date item=%s "
                "media_id=%s date=%s precision=%s source=%s",
                item.id,
                item.media_id,
                parsed.normalized,
                parsed.precision,
                source,
            )
        else:
            stats.updated = 1
            logger.info(
                "Anime release date scan detected updated date item=%s media_id=%s "
                "old=%s new=%s source=%s",
                item.id,
                item.media_id,
                old_text,
                parsed.normalized,
                source,
            )

        delivery_stats = self._deliver_transition(
            item=item,
            users=users,
            parsed=parsed,
            old_text=old_text,
            old_precision=old_precision,
            change_kind=change_kind,
            detected_at=now,
        )
        stats.merge(delivery_stats)
        return stats

    def _deliver_transition(
        self,
        *,
        item,
        users,
        parsed,
        old_text,
        old_precision,
        change_kind,
        detected_at,
    ) -> AnimeReleaseDateScanStats:
        stats = AnimeReleaseDateScanStats()
        previous_parsed = parse_mal_start_date(old_text)
        for user in users:
            delivery, _ = AnimeReleaseDateNotificationDelivery.objects.get_or_create(
                user=user,
                item=item,
                previous_start_date_text=old_text,
                start_date_text=parsed.normalized,
                defaults={
                    "start_date_precision": parsed.precision,
                    "previous_start_date_precision": old_precision,
                    "start_date": parsed.date_value,
                    "previous_start_date": (
                        previous_parsed.date_value if previous_parsed else None
                    ),
                    "change_kind": change_kind,
                    "detected_at": detected_at,
                },
            )
            if delivery.sent_at is not None:
                continue

            urls = [
                url.strip()
                for url in user.notification_urls.splitlines()
                if url.strip()
            ]
            title, body = self._notification_text(
                item.title,
                parsed,
                old_text,
                change_kind,
            )
            sent = send_user_notification(user, urls, title, body)
            if sent:
                delivery.sent_at = timezone.now()
                delivery.failed_at = None
                delivery.error = ""
                delivery.save(update_fields=["sent_at", "failed_at", "error"])
                stats.notifications_sent += 1
                logger.info(
                    "Anime release date notification sent user=%s media_id=%s "
                    "date=%s",
                    user.id,
                    item.media_id,
                    parsed.normalized,
                )
            else:
                delivery.failed_at = timezone.now()
                delivery.error = "Notification delivery failed"
                delivery.save(update_fields=["failed_at", "error"])
                stats.notifications_failed += 1
                logger.error(
                    "Anime release date notification failed user=%s media_id=%s "
                    "date=%s error=%s",
                    user.id,
                    item.media_id,
                    parsed.normalized,
                    delivery.error,
                )
        return stats

    def _mark_error(self, state, error: Exception) -> None:
        state.refresh_from_db()
        state.last_checked_at = timezone.now()
        state.consecutive_error_count += 1
        state.next_scan_at = timezone.now() + timedelta(
            hours=settings.ANIME_RELEASE_DATE_SCAN_ERROR_RETRY_HOURS,
            minutes=self._jitter(120),
        )
        state.save(
            update_fields=[
                "last_checked_at",
                "consecutive_error_count",
                "next_scan_at",
            ],
        )
        logger.warning(
            "Anime release date scan provider error media_id=%s error=%s",
            state.item.media_id,
            str(error)[:250],
        )

    def _finish_state_schedule(self, state, parsed, mal_status, *, now) -> None:
        if mal_status.strip().lower() == "finished":
            state.disabled = True
            return
        state.next_scan_at = self._next_scan_at(
            now=now,
            parsed=parsed,
            stable_scans=state.consecutive_stable_scans,
        )

    @staticmethod
    def _store_parsed_date(state, parsed) -> None:
        if parsed is None:
            return
        state.last_seen_start_date_text = parsed.normalized
        state.last_seen_start_date_precision = parsed.precision
        state.last_seen_start_date = parsed.date_value

    @staticmethod
    def _is_mal_anime(item) -> bool:
        return (
            item.source == Sources.MAL.value
            and item.media_type == MediaTypes.ANIME.value
        )

    @staticmethod
    def _is_definitively_past(parsed, today: date) -> bool:
        if parsed.precision == AnimeStartDatePrecision.DAY:
            return parsed.date_value < today
        if parsed.precision == AnimeStartDatePrecision.MONTH:
            return (parsed.sort_year, parsed.sort_month) < (today.year, today.month)
        return parsed.sort_year < today.year

    @staticmethod
    def _next_scan_at(*, now, parsed, stable_scans):
        max_days = settings.ANIME_RELEASE_DATE_SCAN_MAX_BACKOFF_DAYS
        if parsed is not None:
            return now + timedelta(
                days=max_days,
                hours=AnimeReleaseDateNotificationService._jitter(72),
            )
        if stable_scans >= LONG_BACKOFF_STABLE_SCANS:
            return now + timedelta(
                days=max_days,
                hours=AnimeReleaseDateNotificationService._jitter(72),
            )
        if stable_scans >= MEDIUM_BACKOFF_STABLE_SCANS:
            return now + timedelta(
                days=3,
                hours=AnimeReleaseDateNotificationService._jitter(24),
            )
        return now + timedelta(
            hours=24 + AnimeReleaseDateNotificationService._jitter(6),
        )

    @staticmethod
    def _jitter(maximum: int) -> int:
        """Return an inclusive non-cryptographic scheduling jitter."""
        return secrets.randbelow(maximum + 1)

    @staticmethod
    def _notification_text(title, parsed, old_text, change_kind):
        if (
            change_kind
            == AnimeReleaseDateNotificationDelivery.ChangeKind.ANNOUNCED
        ):
            if parsed.precision == AnimeStartDatePrecision.YEAR:
                start_text = f"in {parsed.normalized}"
            elif parsed.precision == AnimeStartDatePrecision.MONTH:
                month_name = date(
                    parsed.sort_year,
                    parsed.sort_month,
                    1,
                ).strftime("%B")
                start_text = f"in {month_name} {parsed.sort_year}"
            else:
                start_text = f"on {parsed.normalized}"
            return (
                "📅 YamTrack: Anime release date announced",
                f"{title} is scheduled to start {start_text}.",
            )

        return (
            "📅 YamTrack: Anime release date updated",
            f"{title} changed from {old_text} to {parsed.normalized}.",
        )
