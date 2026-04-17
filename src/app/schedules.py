"""Helpers for Celery Beat schedule entries."""

from __future__ import annotations


def build_anime_franchise_import_schedule(
    *,
    enabled: bool,
    interval_minutes: int,
    profile: str,
    refresh_cache: bool = False,
    full_rescan: bool = False,
    limit: int | None = None,
) -> dict:
    """Return optional Celery Beat entry for automatic anime franchise imports."""
    if not enabled:
        return {}

    kwargs = {
        "profile_key": profile,
        "refresh_cache": refresh_cache,
        "full_rescan": full_rescan,
    }
    if limit is not None:
        kwargs["limit"] = limit

    return {
        "auto_import_anime_franchise": {
            "task": "Import anime franchise",
            "schedule": 60 * interval_minutes,
            "kwargs": kwargs,
        },
    }
