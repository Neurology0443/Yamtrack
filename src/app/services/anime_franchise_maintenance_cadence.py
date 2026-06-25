"""Adaptive success cadence policy for MAL anime franchise maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

HOT = "HOT"
WARM = "WARM"
COOL = "COOL"
COLD = "COLD"
DEEP_COLD = "DEEP_COLD"
_ALLOWED_PROFILES = {HOT, WARM, COOL, COLD, DEEP_COLD}


@dataclass(frozen=True)
class FranchiseActivitySummary:
    """Activity signals used to classify a full MAL anime franchise."""

    has_airing: bool
    has_upcoming: bool
    has_future_start: bool
    newest_start_date: date | None
    newest_end_date: date | None
    all_known_finished: bool
    has_unknown_end_dates: bool
    is_truncated: bool


@dataclass(frozen=True)
class ScanWindow:
    """Deterministic scheduling window for a maintenance success."""

    profile: str
    reason: str
    min_minutes: int
    max_minutes: int
    micro_jitter_minutes: int = 0


def summarize_franchise_activity(snapshot, *, now) -> FranchiseActivitySummary:
    """Summarize activity signals across the full canonical franchise snapshot."""
    today = timezone.localdate(now)
    newest_start_date = None
    newest_end_date = None
    has_airing = False
    has_upcoming = False
    has_future_start = False
    has_unknown_end_dates = False

    for node in getattr(snapshot, "nodes_by_media_id", {}).values():
        raw_status = str(getattr(node, "mal_raw_status", "") or "").strip().lower()
        readable_status = str(getattr(node, "mal_status", "") or "").strip().lower()
        has_airing = (
            has_airing
            or raw_status == "currently_airing"
            or readable_status in {"airing", "currently airing"}
        )
        has_upcoming = (
            has_upcoming
            or raw_status == "not_yet_aired"
            or readable_status in {"upcoming", "not yet aired"}
        )

        start_date = getattr(node, "start_date", None)
        if start_date is not None:
            newest_start_date = (
                max(newest_start_date, start_date)
                if newest_start_date
                else start_date
            )
            has_future_start = has_future_start or start_date > today

        end_date = getattr(node, "end_date", None)
        if end_date is None:
            has_unknown_end_dates = True
        else:
            newest_end_date = (
                max(newest_end_date, end_date)
                if newest_end_date
                else end_date
            )

    return FranchiseActivitySummary(
        has_airing=has_airing,
        has_upcoming=has_upcoming,
        has_future_start=has_future_start,
        newest_start_date=newest_start_date,
        newest_end_date=newest_end_date,
        all_known_finished=not has_unknown_end_dates and newest_end_date is not None,
        has_unknown_end_dates=has_unknown_end_dates,
        is_truncated=bool(getattr(snapshot, "is_truncated", False)),
    )


def compute_success_scan_window(  # noqa: C901, PLR0911
    *, activity_summary=None, snapshot=None, state, result, now
) -> ScanWindow:
    """Return the adaptive success scan window for a maintained franchise."""
    summary = activity_summary or getattr(result, "activity_summary", None)
    if summary is None:
        if snapshot is None:
            return _window(WARM, "fallback")
        summary = summarize_franchise_activity(snapshot, now=now)

    if bool(
        getattr(result, "changed", False)
        or getattr(result, "root_changed", False)
    ):
        return _window(HOT, "changed")
    if summary.has_airing or summary.has_upcoming or summary.has_future_start:
        return _window(HOT, "active_or_future")
    if summary.newest_end_date is None:
        return _window(WARM, "unknown_end_date")

    age_days = (timezone.localtime(now).date() - summary.newest_end_date).days
    if age_days < 3 * 365:
        return _window(WARM, "recent")
    if age_days < 10 * 365:
        return _window(COOL, "mature")
    if age_days < _deep_cold_min_age_years() * 365:
        return _window(COLD, "old")
    if summary.has_unknown_end_dates:
        return _window(COLD, "old_with_unknown_end_dates")

    if _deep_cold_allowed(summary=summary, state=state, result=result, now=now):
        return _window(DEEP_COLD, "deep_cold")
    return _window(COLD, "old_not_stable_enough")


def _deep_cold_allowed(*, summary, state, result, now) -> bool:  # noqa: PLR0911
    if summary.is_truncated or summary.has_unknown_end_dates:
        return False
    if summary.has_airing or summary.has_upcoming or summary.has_future_start:
        return False
    if not getattr(state, "component_root_mal_id", ""):
        return False
    if str(getattr(state, "component_root_mal_id", "")) != str(
        getattr(result, "component_root_mal_id", "")
    ):
        return False
    if str(getattr(state, "last_result_fingerprint", "")) != str(
        getattr(result, "maintenance_fingerprint", "")
    ):
        return False
    if getattr(state, "consecutive_stable_scans", 0) < _deep_cold_min_stable_scans():
        return False
    last_change_at = getattr(state, "last_change_at", None)
    if last_change_at is None:
        return True
    return last_change_at <= now - timedelta(days=_deep_cold_min_change_age_days())


def _window(profile: str, reason: str) -> ScanWindow:
    if profile not in _ALLOWED_PROFILES:
        message = f"Unsupported cadence profile: {profile}"
        raise ValueError(message)
    if profile == HOT:
        return ScanWindow(profile, reason, 6 * 60, 36 * 60, 15)
    if profile == WARM:
        return ScanWindow(profile, reason, 24 * 60, 3 * 24 * 60, 120)
    if profile == COOL:
        return ScanWindow(profile, reason, 3 * 24 * 60, 10 * 24 * 60, 240)
    if profile == COLD:
        return ScanWindow(profile, reason, 10 * 24 * 60, 21 * 24 * 60, 360)
    if profile == DEEP_COLD:
        return ScanWindow(
            profile,
            reason,
            _deep_cold_min_days() * 24 * 60,
            _deep_cold_max_days() * 24 * 60,
            720,
        )
    message = f"Unsupported cadence profile without configured window: {profile}"
    raise ValueError(message)


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _deep_cold_min_age_years() -> int:
    return max(
        15,
        _int_setting("ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_AGE_YEARS", 15),
    )


def _deep_cold_min_stable_scans() -> int:
    return max(
        4,
        _int_setting("ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_STABLE_SCANS", 8),
    )


def _deep_cold_min_change_age_days() -> int:
    return max(
        0,
        _int_setting(
            "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_CHANGE_AGE_DAYS", 180
        ),
    )


def _deep_cold_min_days() -> int:
    configured = _int_setting(
        "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_DAYS",
        21,
    )
    return min(30, max(21, configured))


def _deep_cold_max_days() -> int:
    min_days = _deep_cold_min_days()
    configured = _int_setting(
        "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MAX_DAYS",
        30,
    )
    return min(30, max(min_days, configured))
