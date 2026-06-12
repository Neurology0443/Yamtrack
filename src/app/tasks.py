import logging
import time
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from app.models import UserMessage
from app.providers import mal, mal_cache, services
from app.services import anime_franchise_cache
from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_context import serialize_franchise_payload
from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder
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
        mal_cache.mark_refresh_attempt(media_id)
        mal.anime(media_id, refresh_cache=True)
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
            "cache_warm_scheduled": stats.cache_warm_scheduled,
            "cache_warm_roots": stats.cache_warm_roots,
            "cache_warm_errors": stats.cache_warm_errors,
        }

        logger.info("Anime franchise import completed: %s", result)
        return result
    finally:
        cache.delete(lock_key)


@shared_task(name="Build MAL anime franchise payload")
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

    started_at = time.monotonic()
    try:
        anime_franchise_cache.mark_attempt(media_id)
        graph_builder = AnimeFranchiseGraphBuilder(
            max_nodes=settings.ANIME_FRANCHISE_MAX_NODES,
        )
        franchise_payload = AnimeFranchiseService(
            graph_builder=graph_builder,
        ).build(media_id)
        truncated = bool(graph_builder.truncated)
        aliases_enabled = settings.ANIME_FRANCHISE_CACHE_ALIASES_ENABLED
        can_use_aliases = aliases_enabled and not truncated
        truncation_reason = graph_builder.truncation_reason or ""
        node_count = graph_builder.node_count
        serialized_payload = serialize_franchise_payload(
            franchise_payload,
            root_media_id=media_id,
        )
        canonical_payload, canonical_media_id, _aliasable_media_ids = (
            anime_franchise_cache.prepare_payload_for_aliasing(
                serialized_payload,
                build_seed_media_id=media_id,
                truncated=truncated,
                aliases_enabled=aliases_enabled,
            )
        )
        duration = time.monotonic() - started_at
        anime_franchise_cache.save_payload(
            canonical_media_id,
            canonical_payload,
            fetched_at=timezone.now(),
            node_count=node_count,
            build_duration_seconds=duration,
            truncated=truncated,
            truncation_reason=truncation_reason,
        )
        alias_count = 0
        if can_use_aliases:
            alias_count = anime_franchise_cache.replace_aliases(
                canonical_media_id,
                canonical_payload,
                truncated=False,
            )
        if truncated:
            logger.info(
                "MAL anime franchise build truncated for media_id=%s max_nodes=%s",
                media_id,
                settings.ANIME_FRANCHISE_MAX_NODES,
            )
        logger.info(
            "MAL anime franchise build completed for media_id=%s canonical_media_id=%s "
            "nodes=%s duration=%s truncated=%s aliases=%s",
            media_id,
            canonical_media_id,
            node_count,
            round(duration, 3),
            truncated,
            alias_count,
        )
        return {  # noqa: TRY300 - task returns structured success payloads
            "media_id": media_id,
            "canonical_media_id": canonical_media_id,
            "built": True,
            "node_count": node_count,
            "duration": duration,
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "alias_count": alias_count,
        }
    except Exception as error:  # noqa: BLE001 - background task must isolate failures
        error_message = str(error) or error.__class__.__name__
        anime_franchise_cache.mark_error(media_id, error_message)
        logger.warning(
            "MAL anime franchise build failed for media_id=%s: %s",
            media_id,
            error_message,
        )
        return {
            "media_id": media_id,
            "built": False,
            "error": error_message[:250],
        }
    finally:
        cache.delete(task_lock_key)
        cache.delete(anime_franchise_cache.get_queue_lock_key(media_id))
