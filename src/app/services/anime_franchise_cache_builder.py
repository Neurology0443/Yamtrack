"""Reusable builder for the user-agnostic MAL anime franchise UI cache."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class _SnapshotContext:
    snapshot: Any
    media_id: str
    canonical_media_id: str
    truncated: bool
    truncation_reason: str
    node_count: int


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
        force_cache_rebuild=False,
    ) -> dict:
        """Build and save UI cache payloads.

        force_cache_rebuild only bypasses the existing-alias shortcut for the
        user-agnostic UI cache. It does not force MAL API refreshes; MAL
        freshness is controlled exclusively by refresh_cache.
        """
        media_id = str(media_id)
        started_at = time.monotonic()
        try:
            anime_franchise_cache.mark_attempt(media_id)
            snapshot_service = self.build_session.snapshot_service()
            snapshot = snapshot_service.build(media_id, refresh_cache=refresh_cache)
            return self.build_and_save_from_snapshot(
                media_id,
                snapshot=snapshot,
                graph_builder=snapshot_service.graph_builder,
                refresh_cache=refresh_cache,
                force_cache_rebuild=force_cache_rebuild,
                started_at=started_at,
                mark_attempt=False,
            )
        except Exception as error:  # noqa: BLE001
            error_message = str(error) or error.__class__.__name__
            anime_franchise_cache.mark_error(media_id, error_message)
            logger.warning(
                "MAL anime franchise build failed for media_id=%s: %s",
                media_id,
                error_message,
            )
            return {"media_id": media_id, "built": False, "error": error_message[:250]}

    def build_and_save_from_snapshot(
        self,
        media_id,
        *,
        snapshot,
        graph_builder=None,
        refresh_cache: bool | None = None,
        force_cache_rebuild=False,
        started_at=None,
        mark_attempt=True,
    ) -> dict:
        """Save UI cache payloads from an already-built franchise snapshot.

        started_at may be supplied by an orchestrator that performed source
        snapshot preparation before entering the cache publication phase.
        """
        media_id = str(media_id)
        started_at = started_at if started_at is not None else time.monotonic()

        def elapsed() -> float:
            return time.monotonic() - started_at

        try:
            if mark_attempt:
                anime_franchise_cache.mark_attempt(media_id)
            if graph_builder is None:
                error_message = (
                    "graph_builder is required when saving a prebuilt snapshot"
                )
                raise ValueError(error_message)  # noqa: TRY301

            effective_refresh_cache = self._resolve_effective_refresh_cache(
                refresh_cache=refresh_cache
            )
            aliases_enabled = settings.ANIME_FRANCHISE_CACHE_ALIASES_ENABLED
            source_context = self._snapshot_context(
                snapshot=snapshot,
                graph_builder=graph_builder,
                media_id=media_id,
            )

            existing_alias_result = self._valid_alias_result(
                source_context,
                force_cache_rebuild=force_cache_rebuild,
                elapsed=elapsed,
            )
            if existing_alias_result is not None:
                return existing_alias_result

            if not aliases_enabled or source_context.truncated:
                return self._build_and_save_seed_local_payload(
                    source_context,
                    aliases_enabled=aliases_enabled,
                    elapsed=elapsed,
                )

            if self._requires_forced_canonical_rebuild(
                source_context,
                force_cache_rebuild=force_cache_rebuild,
            ):
                return self._build_save_forced_canonical_payload(
                    source_context,
                    effective_refresh_cache=effective_refresh_cache,
                    aliases_enabled=aliases_enabled,
                    elapsed=elapsed,
                )

            if source_context.media_id == source_context.canonical_media_id:
                return self._build_save_canonical_context_payload(
                    source_context,
                    source_context=source_context,
                    aliases_enabled=aliases_enabled,
                    elapsed=elapsed,
                )

            return self._handle_noncanonical_without_forced_rebuild(
                source_context,
                aliases_enabled=aliases_enabled,
                elapsed=elapsed,
            )
        except Exception as error:  # noqa: BLE001
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
                "duration": elapsed(),
            }

    def _resolve_effective_refresh_cache(self, *, refresh_cache: bool | None) -> bool:
        if refresh_cache is None:
            return bool(self.build_session.refresh_cache)
        return bool(refresh_cache)

    def _snapshot_context(self, *, snapshot, graph_builder, media_id: str):
        return _SnapshotContext(
            snapshot=snapshot,
            media_id=str(media_id),
            canonical_media_id=str(snapshot.canonical_root_media_id),
            truncated=bool(graph_builder.truncated),
            truncation_reason=graph_builder.truncation_reason or "",
            node_count=graph_builder.node_count,
        )

    def _valid_alias_result(self, source_context, *, force_cache_rebuild, elapsed):
        if force_cache_rebuild:
            return None
        existing_alias_lookup = (
            anime_franchise_cache.load_valid_alias_payload_for_media(
                source_context.media_id
            )
        )
        if existing_alias_lookup is None:
            return None
        anime_franchise_cache.delete_direct_payload(source_context.media_id)
        return {
            "media_id": source_context.media_id,
            "canonical_media_id": existing_alias_lookup.canonical_media_id,
            "built": True,
            "skipped_direct_write": True,
            "reason": "valid_alias_exists",
            "node_count": source_context.node_count,
            "duration": elapsed(),
            "truncated": source_context.truncated,
            "truncation_reason": source_context.truncation_reason,
            "alias_count": 0,
        }

    def _requires_forced_canonical_rebuild(
        self,
        source_context,
        *,
        force_cache_rebuild,
    ) -> bool:
        return bool(
            force_cache_rebuild
            and source_context.media_id != source_context.canonical_media_id
        )

    def _build_canonical_snapshot_context(
        self,
        source_context,
        *,
        effective_refresh_cache: bool,
    ):
        canonical_snapshot_service = self.build_session.snapshot_service()
        canonical_snapshot = canonical_snapshot_service.build(
            source_context.canonical_media_id,
            refresh_cache=effective_refresh_cache,
        )
        canonical_context = self._snapshot_context(
            snapshot=canonical_snapshot,
            graph_builder=canonical_snapshot_service.graph_builder,
            media_id=source_context.canonical_media_id,
        )
        if canonical_context.truncated:
            reason = canonical_context.truncation_reason or "unknown"
            error_message = f"canonical_snapshot_truncated:{reason}"
            raise RuntimeError(error_message)
        if canonical_context.canonical_media_id != source_context.canonical_media_id:
            error_message = "canonical_root_changed"
            raise RuntimeError(error_message)
        return canonical_context

    def _build_serialized_payload(
        self,
        context,
        *,
        root_media_id: str,
        build_seed_media_id: str,
        aliases_enabled: bool,
    ):
        franchise_payload = AnimeFranchiseUiPipeline().run(context.snapshot)
        serialized_payload = serialize_franchise_payload(
            franchise_payload,
            root_media_id=root_media_id,
        )
        return anime_franchise_cache.prepare_payload_for_aliasing(
            serialized_payload,
            build_seed_media_id=build_seed_media_id,
            truncated=context.truncated,
            aliases_enabled=aliases_enabled,
        )

    def _build_and_save_seed_local_payload(
        self,
        source_context,
        *,
        aliases_enabled: bool,
        elapsed,
    ):
        payload, canonical_media_id, _aliasable = self._build_serialized_payload(
            source_context,
            root_media_id=source_context.media_id,
            build_seed_media_id=source_context.media_id,
            aliases_enabled=aliases_enabled,
        )
        save_duration = elapsed()
        anime_franchise_cache.save_payload(
            canonical_media_id,
            payload,
            fetched_at=timezone.now(),
            node_count=source_context.node_count,
            build_duration_seconds=save_duration,
            truncated=source_context.truncated,
            truncation_reason=source_context.truncation_reason,
        )
        return {
            "media_id": source_context.media_id,
            "canonical_media_id": canonical_media_id,
            "built": True,
            "node_count": source_context.node_count,
            "duration": elapsed(),
            "truncated": source_context.truncated,
            "truncation_reason": source_context.truncation_reason,
            "alias_count": 0,
        }

    def _build_save_forced_canonical_payload(
        self,
        source_context,
        *,
        effective_refresh_cache: bool,
        aliases_enabled: bool,
        elapsed,
    ):
        canonical_context = self._build_canonical_snapshot_context(
            source_context,
            effective_refresh_cache=effective_refresh_cache,
        )
        return self._build_save_canonical_context_payload(
            canonical_context,
            source_context=source_context,
            aliases_enabled=aliases_enabled,
            elapsed=elapsed,
        )

    def _build_save_canonical_context_payload(
        self,
        canonical_context,
        *,
        source_context,
        aliases_enabled: bool,
        elapsed,
    ):
        canonical_payload, canonical_media_id, _aliasable = (
            self._build_serialized_payload(
                canonical_context,
                root_media_id=source_context.canonical_media_id,
                build_seed_media_id=source_context.media_id,
                aliases_enabled=aliases_enabled,
            )
        )
        if canonical_media_id != source_context.canonical_media_id:
            error_message = "canonical_payload_root_mismatch"
            raise RuntimeError(error_message)
        canonical_aliasable_ids = {
            str(aliasable_media_id)
            for aliasable_media_id in canonical_payload.get("aliasable_media_ids", [])
        }
        source_is_canonical = source_context.media_id == canonical_media_id
        source_is_aliasable = source_context.media_id in canonical_aliasable_ids
        prepared_scoped_payload = self._prepare_scoped_payload(
            source_context,
            canonical_media_id=canonical_media_id,
            canonical_aliasable_ids=canonical_aliasable_ids,
        )

        save_duration = elapsed()
        anime_franchise_cache.save_payload(
            canonical_media_id,
            canonical_payload,
            fetched_at=timezone.now(),
            node_count=canonical_context.node_count,
            build_duration_seconds=save_duration,
            truncated=canonical_context.truncated,
            truncation_reason=canonical_context.truncation_reason,
        )
        alias_count = self._replace_aliases_if_allowed(
            canonical_media_id,
            canonical_payload,
            aliases_enabled=aliases_enabled,
            truncated=canonical_context.truncated,
        )
        if not source_is_canonical:
            if source_is_aliasable:
                anime_franchise_cache.delete_direct_payload(source_context.media_id)
            else:
                self._publish_prepared_scoped_payload(
                    source_context,
                    prepared_scoped_payload,
                    elapsed=elapsed,
                )
        return {
            "media_id": source_context.media_id,
            "canonical_media_id": canonical_media_id,
            "built": True,
            "node_count": canonical_context.node_count,
            "duration": elapsed(),
            "truncated": canonical_context.truncated,
            "truncation_reason": canonical_context.truncation_reason,
            "alias_count": alias_count,
        }

    def _handle_noncanonical_without_forced_rebuild(
        self,
        source_context,
        *,
        aliases_enabled: bool,
        elapsed,
    ):
        canonical_payload, existing_canonical_meta = anime_franchise_cache.load_payload(
            source_context.canonical_media_id
        )
        if canonical_payload:
            alias_count = self._replace_aliases_if_allowed(
                source_context.canonical_media_id,
                canonical_payload,
                aliases_enabled=aliases_enabled,
                truncated=False,
            )
        else:
            alias_count = 0
            anime_franchise_cache.maybe_schedule_build(
                source_context.canonical_media_id,
                existing_canonical_meta,
                has_payload=False,
            )
        canonical_aliasable_ids = {
            str(aliasable_media_id)
            for aliasable_media_id in (canonical_payload or {}).get(
                "aliasable_media_ids",
                [],
            )
        }
        prepared_scoped_payload = self._prepare_scoped_payload(
            source_context,
            canonical_media_id=source_context.canonical_media_id,
            canonical_aliasable_ids=canonical_aliasable_ids,
        )
        if source_context.media_id in canonical_aliasable_ids:
            anime_franchise_cache.delete_direct_payload(source_context.media_id)
        else:
            self._publish_prepared_scoped_payload(
                source_context,
                prepared_scoped_payload,
                elapsed=elapsed,
            )
        return {
            "media_id": source_context.media_id,
            "canonical_media_id": source_context.canonical_media_id,
            "built": True,
            "node_count": source_context.node_count,
            "duration": elapsed(),
            "truncated": source_context.truncated,
            "truncation_reason": source_context.truncation_reason,
            "alias_count": alias_count,
        }

    def _replace_aliases_if_allowed(
        self,
        canonical_media_id,
        canonical_payload,
        *,
        aliases_enabled: bool,
        truncated: bool,
    ) -> int:
        if not aliases_enabled or truncated or not canonical_payload:
            return 0
        return anime_franchise_cache.replace_aliases(
            canonical_media_id,
            canonical_payload,
            truncated=False,
        )

    def _prepare_scoped_payload(
        self,
        source_context,
        *,
        canonical_media_id: str,
        canonical_aliasable_ids: set[str],
    ):
        if source_context.media_id == canonical_media_id:
            return None
        if source_context.media_id in canonical_aliasable_ids:
            return None

        scoped_payload = build_scoped_seed_payload_from_snapshot(
            source_context.snapshot,
            seed_media_id=source_context.media_id,
        )
        if scoped_payload is None:
            return None
        scoped_node_count = len(
            anime_franchise_cache.extract_payload_media_ids(scoped_payload),
        )
        return scoped_payload, scoped_node_count

    def _publish_prepared_scoped_payload(
        self,
        source_context,
        prepared_scoped_payload,
        *,
        elapsed,
    ):
        if prepared_scoped_payload is None:
            return
        scoped_payload, scoped_node_count = prepared_scoped_payload
        anime_franchise_cache.save_payload(
            source_context.media_id,
            scoped_payload,
            fetched_at=timezone.now(),
            node_count=scoped_node_count,
            build_duration_seconds=elapsed(),
            truncated=False,
            truncation_reason="",
        )
