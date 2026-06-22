import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from app.anime_series_view_constants import (
    DELETE_MODE,
    REFRESH_MODE,
    REFRESH_MODES,
)
from app.models import UserMessage
from app.providers import mal, mal_cache, services
from app.services import anime_franchise_cache
from app.services.anime_franchise_build_session import AnimeFranchiseBuildSession
from app.services.anime_franchise_cache_builder import AnimeFranchiseCacheBuildService
from app.services.anime_franchise_import import AnimeFranchiseImportService
from app.services.anime_franchise_manual_add_triggers import manual_add_queue_lock_key
from app.services.anime_franchise_task_names import (
    MAL_ANIME_FRANCHISE_BUILD_TASK_NAME,
)
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshService,
)
from app.services.anime_series_view_projection import AnimeSeriesViewProjectionBuilder
from app.services.anime_series_view_refresh_queue import (
    normalize_media_ids,
    refresh_queue_lock_key,
)

logger = logging.getLogger(__name__)


@shared_task(name="Cleanup user messages")
def cleanup_user_messages():
    """Delete shown user messages older than the configured retention window."""
    cutoff = timezone.now() - timedelta(days=settings.USER_MESSAGE_RETENTION_DAYS)
    deleted_count, _ = UserMessage.objects.filter(
        shown_at__isnull=False,
        shown_at__lt=cutoff,
    ).delete()

    logger.info("Deleted %s old shown user messages.", deleted_count)

    return deleted_count


@shared_task(name="Refresh Anime Series View franchise projection")
def refresh_anime_series_view_franchise_projection(
    user_id,
    media_ids,
    mode=REFRESH_MODE,
):
    """Refresh persisted Anime Series View memberships for one user."""
    normalized_ids = normalize_media_ids(media_ids)
    lock_key = refresh_queue_lock_key(user_id, normalized_ids, mode)
    try:
        if not normalized_ids:
            return {
                "user_id": user_id,
                "media_ids": [],
                "mode": mode,
                "refreshed": False,
                "skipped": True,
                "reason": "empty_media_ids",
            }
        if mode not in REFRESH_MODES:
            return {
                "user_id": user_id,
                "media_ids": list(normalized_ids),
                "mode": mode,
                "refreshed": False,
                "skipped": True,
                "reason": "invalid_mode",
            }

        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return {
                "user_id": user_id,
                "media_ids": list(normalized_ids),
                "mode": mode,
                "refreshed": False,
                "skipped": True,
                "reason": "user_not_found",
            }

        logger.info(
            "Starting Anime Series View franchise projection refresh",
            extra={"user_id": user_id, "media_ids": list(normalized_ids)},
        )
        service = AnimeSeriesViewFranchiseRefreshService()
        if mode == DELETE_MODE:
            stats = service.refresh_after_delete(
                user=user,
                media_ids=normalized_ids,
            )
        else:
            stats = service.refresh_for_media_ids(
                user=user,
                media_ids=normalized_ids,
            )
    except Exception:
        logger.exception(
            "Anime Series View franchise projection refresh failed",
            extra={"user_id": user_id, "media_ids": list(normalized_ids)},
        )
        raise
    else:
        result = {
            "user_id": user_id,
            "media_ids": list(normalized_ids),
            "mode": mode,
            "refreshed": True,
            "requested": stats.requested,
            "snapshots_built": stats.snapshots_built,
            "snapshots_skipped": stats.snapshots_skipped,
            "franchise_memberships_created": stats.franchise_memberships_created,
            "franchise_memberships_updated": stats.franchise_memberships_updated,
            "singleton_memberships_created": stats.singleton_memberships_created,
            "singleton_memberships_updated": stats.singleton_memberships_updated,
            "memberships_deleted": stats.memberships_deleted,
            "errors": stats.errors,
        }
        logger.info(
            "Completed Anime Series View franchise projection refresh",
            extra=result,
        )
        return result
    finally:
        cache.delete(lock_key)


@shared_task(name="Refresh MAL anime metadata")
def refresh_mal_anime_metadata(media_id):
    """Refresh MAL anime detail metadata in the background."""
    task_lock_key = mal_cache.get_anime_refresh_task_lock_key(media_id)
    task_lock_timeout = 60 * 30

    acquired = cache.add(task_lock_key, "1", timeout=task_lock_timeout)
    if not acquired:
        logger.info(
            "Skipping MAL anime metadata refresh for %s because another run is active.",
            media_id,
        )
        return {
            "media_type": "anime",
            "media_id": str(media_id),
            "refreshed": False,
            "skipped": True,
            "reason": "already_running",
        }

    try:
        old_metadata, _ = mal_cache.load_anime_cache(media_id)
        mal_cache.mark_refresh_attempt(media_id)
        new_metadata = mal.anime(media_id, refresh_cache=True)
        from events.services.anime_release_date_notifications import (  # noqa: PLC0415
            AnimeReleaseDateNotificationService,
        )

        try:
            AnimeReleaseDateNotificationService().process_metadata_refresh(
                media_id=media_id,
                old_metadata=old_metadata,
                new_metadata=new_metadata,
                source="metadata_refresh",
            )
        except Exception:
            logger.exception(
                "Failed to process anime release-date metadata refresh for %s",
                media_id,
            )
        return {
            "media_type": "anime",
            "media_id": str(media_id),
            "refreshed": True,
        }
    except (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
        requests.exceptions.RequestException,
        services.ProviderAPIError,
    ) as error:
        error_message = str(error) or error.__class__.__name__
        mal_cache.mark_refresh_error(media_id, error_message)
        logger.warning(
            "MAL anime metadata refresh failed for %s: %s",
            media_id,
            error_message,
        )
        return {
            "media_type": "anime",
            "media_id": str(media_id),
            "refreshed": False,
            "error": error_message[:250],
        }
    finally:
        cache.delete(task_lock_key)


@shared_task(name="Import anime franchise")
def import_anime_franchise(
    *,
    profile_key="satellites",
    full_rescan=False,
    refresh_cache=False,
    limit=None,
    user_ids=None,
):
    """Run the profile-based anime franchise importer."""
    lock_key = f"anime-franchise-import:{profile_key}"
    lock_timeout = 60 * 60 * 6  # 6 hours, aligned with task time limit

    acquired = cache.add(lock_key, "1", timeout=lock_timeout)
    if not acquired:
        logger.info(
            "Skipping anime franchise import for profile=%s because another run "
            "is active.",
            profile_key,
        )
        return {
            "profile": profile_key,
            "skipped": True,
            "reason": "already_running",
        }

    try:
        build_session = AnimeFranchiseBuildSession(refresh_cache=refresh_cache)
        stats = AnimeFranchiseImportService(
            snapshot_service=build_session.snapshot_service(),
        ).run(
            profile_key=profile_key,
            dry_run=False,
            full_rescan=full_rescan,
            limit=limit,
            refresh_cache=refresh_cache,
            user_ids=user_ids,
        )

        result = {
            "profile": profile_key,
            "scanned": stats.scanned,
            "users_considered": stats.users_considered,
            "distinct_seeds": stats.distinct_seeds,
            "due_selected": stats.due_selected,
            "skipped_not_due": stats.skipped_not_due,
            "created": stats.created,
            "planned_creations": stats.planned_creations,
            "already_exists": stats.already_exists,
            "state_rows_created": stats.state_rows_created,
            "state_rows_updated": stats.state_rows_updated,
            "skipped": stats.skipped,
            "errors": stats.errors,
            "created_ids": stats.created_ids,
            "cache_warm_targets": stats.cache_warm_targets,
            "cache_warm_scheduled": stats.cache_warm_scheduled,
            "cache_warm_roots": stats.cache_warm_roots,
            "cache_warm_errors": stats.cache_warm_errors,
            "discovery_errors": stats.discovery_errors,
        }

        logger.info("Anime franchise import completed: %s", result)
        return result
    finally:
        cache.delete(lock_key)


@shared_task(name=MAL_ANIME_FRANCHISE_BUILD_TASK_NAME)
def build_mal_anime_franchise_payload(media_id):
    """Build and cache the complete MAL anime franchise payload in the background."""
    media_id = str(media_id)
    task_lock_key = anime_franchise_cache.get_task_lock_key(media_id)
    acquired = cache.add(
        task_lock_key,
        "1",
        timeout=anime_franchise_cache.get_task_lock_ttl_seconds(),
    )
    if not acquired:
        logger.info(
            "MAL anime franchise build already running for media_id=%s",
            media_id,
        )
        return {
            "media_id": media_id,
            "built": False,
            "skipped": True,
            "reason": "already_running",
        }

    try:
        return AnimeFranchiseCacheBuildService().build_and_save(media_id)
    finally:
        cache.delete(task_lock_key)
        cache.delete(anime_franchise_cache.get_queue_lock_key(media_id))


@shared_task(name="Process manual MAL anime franchise")
def process_manual_mal_anime_franchise(user_id, media_id):
    """Coordinate franchise cache warm and Series View refresh after add."""
    media_id = str(media_id)
    result = {
        "user_id": user_id,
        "media_id": media_id,
        "cache_ui": {"attempted": True, "success": False},
        "series_view": {"attempted": True, "success": False},
    }
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        result["cache_ui"]["attempted"] = False
        result["series_view"]["attempted"] = False
        result["skipped"] = True
        result["reason"] = "user_not_found"
        cache.delete(manual_add_queue_lock_key(user_id, media_id))
        return result

    build_session = AnimeFranchiseBuildSession()
    cache_service = AnimeFranchiseCacheBuildService(build_session=build_session)
    try:
        cache_result = cache_service.build_and_save(
            media_id,
            refresh_cache=True,
            force=True,
        )
        result["cache_ui"].update(
            {
                "success": bool(cache_result.get("built")),
                "canonical_media_id": cache_result.get("canonical_media_id"),
                "result": cache_result,
            },
        )
    except Exception as error:
        logger.exception(
            "Manual MAL anime franchise cache warm failed",
            extra={"user_id": user_id, "media_id": media_id},
        )
        result["cache_ui"]["error"] = str(error)[:250]

    projection_builder = AnimeSeriesViewProjectionBuilder(
        snapshot_service=build_session.build_series_view_snapshot_service(),
    )
    refresh_service = AnimeSeriesViewFranchiseRefreshService(
        projection_builder=projection_builder,
    )
    try:
        stats = refresh_service.refresh_for_media_ids(
            user=user,
            media_ids=(media_id,),
            refresh_cache=True,
        )
        result["series_view"].update(
            {
                "success": stats.errors == 0,
                "stats": {
                    "requested": stats.requested,
                    "snapshots_built": stats.snapshots_built,
                    "snapshots_skipped": stats.snapshots_skipped,
                    "franchise_memberships_created": (
                        stats.franchise_memberships_created
                    ),
                    "franchise_memberships_updated": (
                        stats.franchise_memberships_updated
                    ),
                    "singleton_memberships_created": (
                        stats.singleton_memberships_created
                    ),
                    "singleton_memberships_updated": (
                        stats.singleton_memberships_updated
                    ),
                    "memberships_deleted": stats.memberships_deleted,
                    "errors": stats.errors,
                },
            },
        )
    except Exception as error:
        logger.exception(
            "Manual MAL anime Series View refresh failed",
            extra={"user_id": user_id, "media_id": media_id},
        )
        result["series_view"]["error"] = str(error)[:250]

    cache.delete(manual_add_queue_lock_key(user_id, media_id))
    return result
