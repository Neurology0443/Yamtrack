import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from app.models import AnimeFranchiseDiscoveredEntry
from app.services.anime_tracking import is_mal_anime_tracked
from events import notifications
from events.calendar.main import fetch_releases

logger = logging.getLogger(__name__)


@shared_task(name="Reload calendar")
def reload_calendar(user=None, items_to_process=None):
    """Refresh the calendar with latest dates for all users."""
    if user:
        logger.info("Reloading calendar for user: %s", user.username)
    else:
        logger.info("Reloading calendar for all users")

    return fetch_releases(
        user=user,
        items_to_process=items_to_process,
    )


@shared_task(name="Send release notifications")
def send_release_notifications():
    """Send notifications for recently released media."""
    logger.info("Starting recent release notification task")

    return notifications.send_releases()


@shared_task(name="Send daily digest")
def send_daily_digest_notifications():
    """Send daily digest of today's releases."""
    logger.info("Starting daily digest task")

    return notifications.send_daily_digest()


@shared_task(name="Send entry added notification")
def send_entry_added_notification_task(user_id, media_label):
    """Send queued entry-added notification to a user."""
    user = get_user_model().objects.filter(id=user_id).first()
    if not user:
        logger.warning(
            "Skipping entry-added notification because user %s does not exist",
            user_id,
        )
        return

    notifications.send_entry_added_notification(user, media_label)


@shared_task(name="Send franchise discovery notification")
def send_franchise_discovery_notification_task(user_id, discovery_id):
    """Send queued MAL franchise discovery notification to a user."""
    lock_key = f"franchise-discovery-notification:{discovery_id}"
    if not cache.add(lock_key, "1", timeout=300):
        return

    try:
        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            logger.warning(
                (
                    "Skipping franchise discovery notification because user %s "
                    "does not exist"
                ),
                user_id,
            )
            return

        discovery = AnimeFranchiseDiscoveredEntry.objects.filter(
            id=discovery_id,
            user_id=user_id,
        ).first()
        if not discovery:
            logger.warning(
                (
                    "Skipping franchise discovery notification because discovery %s "
                    "does not exist for user %s"
                ),
                discovery_id,
                user_id,
            )
            return

        if discovery.notified_at or discovery.notification_suppressed_reason:
            return

        if (
            not user.franchise_discovery_notifications_enabled
            or not user.notification_urls.strip()
        ):
            _set_discovery_suppression_reason(discovery, "notifications_disabled")
            return

        if is_mal_anime_tracked(
            user_id=user_id,
            media_id=discovery.discovered_media_id,
        ):
            _set_discovery_suppression_reason(discovery, "already_tracked")
            return

        sent = notifications.send_franchise_discovery_notification(user, discovery)
        if sent:
            discovery.notified_at = timezone.now()
            discovery.save(update_fields=["notified_at"])
    finally:
        cache.delete(lock_key)


def _set_discovery_suppression_reason(discovery, reason):
    if discovery.notification_suppressed_reason:
        return
    discovery.notification_suppressed_reason = reason
    discovery.save(update_fields=["notification_suppressed_reason"])
