import logging

from celery import shared_task
from django.conf import settings
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


@shared_task(name="Scan MAL anime release dates")
def scan_mal_anime_release_dates():
    """Run the bounded MAL anime release-date scan."""
    if not settings.ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED:
        return {
            "scanned": 0,
            "states_created": 0,
            "initialized": 0,
            "announced": 0,
            "updated": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "errors": 0,
            "skipped": 1,
            "reason": "disabled",
        }

    from events.services.anime_release_date_notifications import (  # noqa: PLC0415
        AnimeReleaseDateNotificationService,
    )

    return AnimeReleaseDateNotificationService().scan_due_items()


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
def send_franchise_discovery_notification_task(user_id, discovery_id):  # noqa: PLR0911
    """Send queued MAL franchise discovery notification to a user."""
    lock_key = f"franchise-discovery-notification:{discovery_id}"
    if not cache.add(lock_key, "1", timeout=300):
        return _franchise_discovery_task_result(
            user_id=user_id,
            discovery_id=discovery_id,
            skipped=True,
            reason="already_running",
        )

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
            return _franchise_discovery_task_result(
                user_id=user_id,
                discovery_id=discovery_id,
                skipped=True,
                reason="user_not_found",
            )

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
            return _franchise_discovery_task_result(
                user_id=user_id,
                discovery_id=discovery_id,
                skipped=True,
                reason="discovery_not_found",
            )

        if discovery.notified_at or discovery.notification_suppressed_reason:
            return _franchise_discovery_task_result(
                user_id=user_id,
                discovery_id=discovery_id,
                skipped=True,
                reason="already_notified_or_suppressed",
                notified_at=(
                    discovery.notified_at.isoformat() if discovery.notified_at else None
                ),
                notification_suppressed_reason=(
                    discovery.notification_suppressed_reason
                ),
                include_suppression_details=True,
            )

        if (
            not user.franchise_discovery_notifications_enabled
            or not user.notification_urls.strip()
        ):
            if discovery.notification_queued_at:
                discovery.notification_queued_at = None
                discovery.save(update_fields=["notification_queued_at"])
            return _franchise_discovery_task_result(
                user_id=user_id,
                discovery_id=discovery_id,
                skipped=True,
                reason="notifications_disabled",
            )

        if is_mal_anime_tracked(
            user_id=user_id,
            media_id=discovery.discovered_media_id,
        ):
            _set_discovery_suppression_reason(discovery, "already_tracked")
            return _franchise_discovery_task_result(
                user_id=user_id,
                discovery_id=discovery_id,
                skipped=True,
                reason="already_tracked",
            )

        sent = notifications.send_franchise_discovery_notification(user, discovery)
        if sent:
            discovery.notified_at = timezone.now()
            discovery.save(update_fields=["notified_at"])
        return _franchise_discovery_task_result(
            user_id=user_id,
            discovery_id=discovery_id,
            sent=bool(sent),
            reason=None if sent else "send_failed",
            discovery=discovery,
        )
    finally:
        cache.delete(lock_key)


def _franchise_discovery_task_result(
    *,
    user_id,
    discovery_id,
    sent=False,
    skipped=False,
    reason=None,
    discovery=None,
    notified_at=None,
    notification_suppressed_reason=None,
    include_suppression_details=False,
):
    result = {
        "sent": sent,
        "skipped": skipped,
        "user_id": user_id,
        "discovery_id": discovery_id,
    }
    if reason:
        result["reason"] = reason
    if discovery is not None:
        result.update(
            {
                "discovered_media_id": discovery.discovered_media_id,
                "title": discovery.title,
                "root_media_id": discovery.component_root_mal_id,
                "component_root_mal_id": discovery.component_root_mal_id,
                "root_title": discovery.root_title,
                "section_label": discovery.section_label,
                "relation_type": discovery.relation_type,
            }
        )
    if include_suppression_details or notified_at is not None:
        result["notified_at"] = notified_at
    if include_suppression_details or notification_suppressed_reason is not None:
        result["notification_suppressed_reason"] = notification_suppressed_reason
    return result


def _set_discovery_suppression_reason(discovery, reason):
    if discovery.notification_suppressed_reason:
        return
    discovery.notification_suppressed_reason = reason
    discovery.save(update_fields=["notification_suppressed_reason"])
