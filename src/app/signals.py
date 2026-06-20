import logging

from celery import states
from celery.signals import before_task_publish
from django.db.backends.signals import connection_created
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django_celery_results.models import TaskResult

from app.models import AnimeImportScanState
from app.services.anime_series_view_refresh_triggers import (
    AnimeSeriesViewRefreshTriggerService,
)

logger = logging.getLogger(__name__)


@receiver(connection_created)
def setup_sqlite_pragmas(sender, connection, **kwargs):  # noqa: ARG001
    """Set up SQLite pragmas for WAL mode and busy timeout on connection creation."""
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=wal;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()


@before_task_publish.connect
def create_task_result_on_publish(sender=None, headers=None, body=None, **kwargs):  # noqa: ARG001
    """Create a TaskResult object with PENDING status on task publish.

    https://github.com/celery/django-celery-results/issues/286#issuecomment-1279161047
    """
    if "task" not in headers:
        return

    TaskResult.objects.store_result(
        content_type="application/json",
        content_encoding="utf-8",
        task_id=headers["id"],
        result=None,
        status=states.PENDING,
        task_name=headers["task"],
        task_args=headers.get("argsrepr", ""),
        task_kwargs=headers.get("kwargsrepr", ""),
    )


@receiver(post_save, sender=AnimeImportScanState)
def refresh_anime_series_view_after_import_batch(
    sender,
    instance,
    **kwargs,
):
    """Refresh once a successful profile batch has recorded its final state."""
    _ = sender, kwargs
    if not getattr(instance, "_series_view_success_changed", False):
        return
    AnimeSeriesViewRefreshTriggerService().schedule_import_batch(
        user=instance.user,
        seed_media_id=instance.seed_mal_id,
        component_root_media_id=instance.component_root_mal_id,
    )


@receiver(pre_save, sender=AnimeImportScanState)
def detect_successful_anime_import_batch(
    sender,
    instance,
    **kwargs,
):
    """Mark only transitions that record a new successful import run."""
    _ = sender, kwargs
    previous_success = None
    if instance.pk:
        previous_success = (
            AnimeImportScanState.objects.filter(pk=instance.pk)
            .values_list("last_success_at", flat=True)
            .first()
        )
    instance._series_view_success_changed = (
        instance.last_success_at is not None
        and instance.last_success_at != previous_success
    )
