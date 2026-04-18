import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from app.models import UserMessage
from app.services.anime_franchise_import import AnimeFranchiseImportService

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
            "Skipping anime franchise import for profile=%s because another run is active.",
            profile_key,
        )
        return {
            "profile": profile_key,
            "skipped": True,
            "reason": "already_running",
        }

    try:
        stats = AnimeFranchiseImportService().run(
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
        }

        logger.info("Anime franchise import completed: %s", result)
        return result
    finally:
        cache.delete(lock_key)
