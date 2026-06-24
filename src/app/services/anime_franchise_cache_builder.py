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
    build_detail_scoped_payload_from_snapshot,
)
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline

logger = logging.getLogger(__name__)


class AnimeFranchiseCacheBuildService:
    """Build and save the existing cache payload shape for one MAL anime franchise."""

    def __init__(self, *, build_session=None):
        """Create the builder with an optional shared build session."""
        self.build_session = build_session or AnimeFranchiseBuildSession()

    def build_and_save(
        self,
        media_id,
        *,
        refresh_cache=False,
    ) -> dict:
        """Build and save user-agnostic global/scoped franchise cache payloads."""
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
                    canonical_media_id=getattr(
                        snapshot, "canonical_root_media_id", None
                    ),
                    truncated=truncated,
                    aliases_enabled=aliases_enabled,
                )
            )
            is_canonical_build = media_id == canonical_media_id
            duration = time.monotonic() - started_at
            if not is_canonical_build:
                # A valid alias is a canonical fallback, not a reason to skip
                # rebuilding/replacing the scoped detail payload for this seed.
                anime_franchise_cache.delete_global_payload(media_id)

            alias_count = 0
            if is_canonical_build:
                canonical_payload.update(
                    {
                        "payload_role": anime_franchise_cache.PAYLOAD_ROLE_GLOBAL,
                        "payload_kind": (
                            anime_franchise_cache.PAYLOAD_KIND_CANONICAL_FRANCHISE
                        ),
                        "build_seed_media_id": media_id,
                        "node_count": node_count,
                        "truncated": truncated,
                        "truncation_reason": truncation_reason,
                    }
                )
                anime_franchise_cache.save_global_payload(
                    canonical_media_id,
                    canonical_payload,
                    meta=anime_franchise_cache.build_payload_meta(
                        canonical_payload,
                        fetched_at=timezone.now(),
                        node_count=node_count,
                        build_duration_seconds=duration,
                        truncated=truncated,
                        truncation_reason=truncation_reason,
                    ),
                )
                alias_count = anime_franchise_cache.sync_aliases_for_global_payload(
                    canonical_media_id,
                    canonical_payload,
                    aliases_enabled=aliases_enabled,
                    truncated=truncated,
                )
            else:
                existing_canonical_lookup = anime_franchise_cache.load_global_payload(
                    canonical_media_id
                )
                existing_canonical_payload = (
                    existing_canonical_lookup.payload
                    if existing_canonical_lookup
                    else None
                )
                if existing_canonical_payload:
                    alias_count = anime_franchise_cache.sync_aliases_for_global_payload(
                        canonical_media_id,
                        existing_canonical_payload,
                        aliases_enabled=aliases_enabled,
                        truncated=bool(
                            existing_canonical_payload.get("truncated")
                            or existing_canonical_lookup.meta.get("truncated")
                        ),
                    )
                else:
                    anime_franchise_cache.maybe_schedule_build(
                        canonical_media_id,
                        payload_meta=None,
                        has_payload=False,
                    )
            scoped_payload = build_detail_scoped_payload_from_snapshot(
                snapshot,
                seed_media_id=media_id,
            )
            if scoped_payload is not None and not is_canonical_build:
                scoped_node_count = len(
                    anime_franchise_cache.extract_payload_media_ids(scoped_payload),
                )
                scoped_payload.update(
                    {
                        "build_seed_media_id": media_id,
                        "global_canonical_root_media_id": canonical_media_id,
                        "node_count": scoped_node_count,
                        "truncated": False,
                        "truncation_reason": "",
                    }
                )
                anime_franchise_cache.save_scoped_payload(
                    media_id,
                    scoped_payload,
                    meta=anime_franchise_cache.build_payload_meta(
                        scoped_payload,
                        fetched_at=timezone.now(),
                        node_count=scoped_node_count,
                        build_duration_seconds=duration,
                    ),
                )
            elif not is_canonical_build:
                anime_franchise_cache.delete_scoped_payload(media_id)

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
