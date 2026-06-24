"""Invalidate MAL anime franchise cache when continuity relations change."""

from __future__ import annotations

import logging

from app.providers import mal
from app.services import anime_franchise_cache
from app.services.anime_franchise_graph import CONTINUITY_RELATIONS

logger = logging.getLogger(__name__)


class AnimeFranchiseContinuityInvalidationService:
    """Handle franchise invalidation after MAL anime detail refresh."""

    def process_metadata_refresh(self, *, media_id, old_metadata, new_metadata) -> dict:
        """Invalidate and schedule franchise rebuild when continuity edges changed."""
        old_edges = self._extract_continuity_edges(old_metadata, media_id)
        new_edges = self._extract_continuity_edges(new_metadata, media_id)

        if old_edges == new_edges:
            return {
                "changed": False,
                "scheduled": False,
            }

        lookup = anime_franchise_cache.load_payload_for_media(media_id)
        canonical_media_id = lookup.canonical_media_id

        if lookup.payload is None:
            logger.info(
                "MAL anime continuity changed for media_id=%s but no franchise "
                "payload exists to invalidate.",
                media_id,
            )
            return {
                "changed": True,
                "scheduled": False,
                "reason": "no_franchise_payload",
                "canonical_media_id": canonical_media_id,
                "old_edges": sorted(old_edges),
                "new_edges": sorted(new_edges),
            }

        meta = anime_franchise_cache.mark_stale(
            canonical_media_id,
            reason="continuity_relations_changed",
            invalidated_by_media_id=media_id,
        )

        scheduled = anime_franchise_cache.maybe_schedule_build(
            canonical_media_id,
            meta,
            has_payload=True,
            force=True,
        )

        logger.info(
            "MAL anime franchise invalidation processed for media_id=%s "
            "canonical_media_id=%s scheduled=%s",
            media_id,
            canonical_media_id,
            scheduled,
        )

        return {
            "changed": True,
            "scheduled": scheduled,
            "canonical_media_id": canonical_media_id,
            "old_edges": sorted(old_edges),
            "new_edges": sorted(new_edges),
        }

    def _extract_continuity_edges(
        self,
        metadata,
        fallback_media_id,
    ) -> set[tuple[str, str, str]]:
        """Return normalized MAL prequel/sequel edges from anime metadata."""
        if not isinstance(metadata, dict):
            return set()

        source_media_id = str(metadata.get("media_id") or fallback_media_id)
        related = metadata.get("related", {}).get("related_anime", [])

        edges = set()
        for relation in related or []:
            if not isinstance(relation, dict):
                continue

            relation_type = mal.normalize_relation_type(
                relation.get("relation_type"),
            )
            target_media_id = relation.get("media_id")

            if relation_type not in CONTINUITY_RELATIONS:
                continue
            if target_media_id in (None, ""):
                continue

            edges.add((source_media_id, str(target_media_id), relation_type))

        return edges
