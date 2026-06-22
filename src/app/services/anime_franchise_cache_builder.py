"""Reusable builder for the user-agnostic MAL anime franchise UI cache."""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.utils import timezone

from app.services import anime_franchise_cache
from app.services.anime_franchise_build_session import AnimeFranchiseBuildSession
from app.services.anime_franchise_context import serialize_franchise_payload
from app.services.anime_franchise_scoped_payload import (
    build_scoped_seed_payload_from_snapshot,
)
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline

logger = logging.getLogger(__name__)


class AnimeFranchiseCacheBuildService:
    """Build and save the existing cache payload shape for one MAL anime franchise."""

    def __init__(self, *, build_session=None):
        """Create the builder with an optional shared build session."""
        self.build_session = build_session or AnimeFranchiseBuildSession()

    def build_and_save(self, media_id, *, refresh_cache=False, force=False) -> dict:
        """Build the UI projection and save canonical/scoped cache payloads."""
        media_id = str(media_id)
        started_at = time.monotonic()
        try:
            anime_franchise_cache.mark_attempt(media_id)
            snapshot_service = self.build_session.snapshot_service()
            snapshot = snapshot_service.build(media_id, refresh_cache=refresh_cache)
            graph_builder = snapshot_service.graph_builder
            franchise_payload = AnimeFranchiseUiPipeline().run(snapshot)
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
            is_canonical_build = media_id == canonical_media_id
            duration = time.monotonic() - started_at
            existing_alias_lookup = (
                None
                if force
                else anime_franchise_cache.load_valid_alias_payload_for_media(media_id)
            )
            if existing_alias_lookup is not None:
                anime_franchise_cache.delete_direct_payload(media_id)
                return {
                    "media_id": media_id,
                    "canonical_media_id": existing_alias_lookup.canonical_media_id,
                    "built": True,
                    "skipped_direct_write": True,
                    "reason": "valid_alias_exists",
                    "node_count": node_count,
                    "duration": duration,
                    "truncated": truncated,
                    "truncation_reason": truncation_reason,
                    "alias_count": 0,
                }

            alias_count = 0
            seed_is_aliasable_in_existing_canonical = False
            if is_canonical_build:
                anime_franchise_cache.save_payload(
                    canonical_media_id,
                    canonical_payload,
                    fetched_at=timezone.now(),
                    node_count=node_count,
                    build_duration_seconds=duration,
                    truncated=truncated,
                    truncation_reason=truncation_reason,
                )
                if can_use_aliases:
                    alias_count = anime_franchise_cache.replace_aliases(
                        canonical_media_id,
                        canonical_payload,
                        truncated=False,
                    )
            else:
                existing_canonical_payload, existing_canonical_meta = (
                    anime_franchise_cache.load_payload(canonical_media_id)
                )
                existing_aliasable_ids = set()
                if existing_canonical_payload:
                    existing_aliasable_ids = {
                        str(aliasable_media_id)
                        for aliasable_media_id in existing_canonical_payload.get(
                            "aliasable_media_ids",
                            [],
                        )
                    }
                    if can_use_aliases:
                        alias_count = anime_franchise_cache.replace_aliases(
                            canonical_media_id,
                            existing_canonical_payload,
                            truncated=False,
                        )
                else:
                    anime_franchise_cache.maybe_schedule_build(
                        canonical_media_id,
                        existing_canonical_meta,
                        has_payload=False,
                    )
                seed_is_aliasable_in_existing_canonical = (
                    media_id in existing_aliasable_ids
                )

            scoped_payload = build_scoped_seed_payload_from_snapshot(
                snapshot,
                seed_media_id=media_id,
            )
            if not is_canonical_build and seed_is_aliasable_in_existing_canonical:
                anime_franchise_cache.delete_direct_payload(media_id)
            if (
                scoped_payload is not None
                and not is_canonical_build
                and not seed_is_aliasable_in_existing_canonical
            ):
                scoped_node_count = len(
                    anime_franchise_cache.extract_payload_media_ids(scoped_payload),
                )
                anime_franchise_cache.save_payload(
                    media_id,
                    scoped_payload,
                    fetched_at=timezone.now(),
                    node_count=scoped_node_count,
                    build_duration_seconds=duration,
                    truncated=False,
                    truncation_reason="",
                )

            return {  # noqa: TRY300
                "media_id": media_id,
                "canonical_media_id": canonical_media_id,
                "built": True,
                "node_count": node_count,
                "duration": duration,
                "truncated": truncated,
                "truncation_reason": truncation_reason,
                "alias_count": alias_count,
            }
        except Exception as error:  # noqa: BLE001
            error_message = str(error) or error.__class__.__name__
            anime_franchise_cache.mark_error(media_id, error_message)
            logger.warning(
                "MAL anime franchise build failed for media_id=%s: %s",
                media_id,
                error_message,
            )
            return {"media_id": media_id, "built": False, "error": error_message[:250]}
