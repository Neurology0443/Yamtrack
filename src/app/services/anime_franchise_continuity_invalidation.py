"""Invalidate MAL anime franchise cache when relevant relations change."""

from __future__ import annotations

import logging

from app.providers import mal
from app.services import anime_franchise_cache
from app.services.anime_franchise_graph import CONTINUITY_RELATIONS
from app.services.anime_franchise_maintenance_scan import (
    AnimeFranchiseMaintenanceScanService,
)

logger = logging.getLogger(__name__)

CONTINUITY_INVALIDATION_RELATIONS = frozenset(CONTINUITY_RELATIONS)

FRANCHISE_STRUCTURE_INVALIDATION_RELATIONS = frozenset(
    {
        "alternative_setting",
        "alternative_version",
        "spin_off",
    }
)

STRONG_INVALIDATION_RELATIONS = (
    CONTINUITY_INVALIDATION_RELATIONS | FRANCHISE_STRUCTURE_INVALIDATION_RELATIONS
)

CONTINUITY_INVALIDATION_REASON = "continuity_relations_changed"
FRANCHISE_STRUCTURE_INVALIDATION_REASON = "franchise_structure_relations_changed"


class AnimeFranchiseContinuityInvalidationService:
    """Handle franchise invalidation after MAL anime detail refresh."""

    def process_metadata_refresh(self, *, media_id, old_metadata, new_metadata) -> dict:
        """Invalidate and schedule franchise rebuild when relevant edges changed."""
        media_id = str(media_id)
        old_edges = self._extract_invalidation_edges(old_metadata, media_id)
        new_edges = self._extract_invalidation_edges(new_metadata, media_id)

        if old_edges == new_edges:
            return {
                "changed": False,
                "scheduled": False,
            }

        changed_edges = old_edges.symmetric_difference(new_edges)
        changed_relation_types = sorted({edge[2] for edge in changed_edges})
        invalidation_reason = self._invalidation_reason(changed_relation_types)
        touched_media_ids = self._media_ids_from_edges(
            media_id=media_id,
            edges=changed_edges,
        )

        source_lookup = anime_franchise_cache.load_payload_for_media(media_id)
        canonical_media_id = str(source_lookup.canonical_media_id or media_id).strip()

        scheduled = False
        invalidated_canonical_media_ids = set()
        missing_payload_media_ids = set()

        for touched_media_id in sorted(touched_media_ids):
            lookup = anime_franchise_cache.load_payload_for_media(touched_media_id)
            touched_canonical_media_id = str(
                lookup.canonical_media_id or touched_media_id
            ).strip()

            if not touched_canonical_media_id:
                missing_payload_media_ids.add(touched_media_id)
                continue

            if lookup.payload is None:
                logger.info(
                    "MAL anime franchise relation changed for media_id=%s but no "
                    "franchise payload exists for touched_media_id=%s.",
                    media_id,
                    touched_media_id,
                )
                missing_payload_media_ids.add(touched_media_id)
                continue

            if touched_canonical_media_id in invalidated_canonical_media_ids:
                continue

            meta = anime_franchise_cache.mark_stale(
                touched_canonical_media_id,
                reason=invalidation_reason,
                invalidated_by_media_id=media_id,
            )
            invalidated_canonical_media_ids.add(touched_canonical_media_id)

            scheduled = (
                anime_franchise_cache.maybe_schedule_build(
                    touched_canonical_media_id,
                    meta,
                    has_payload=True,
                    force=True,
                )
                or scheduled
            )

        maintenance_states_nudged = 0
        media_ids_to_nudge = touched_media_ids | invalidated_canonical_media_ids
        scan_service = AnimeFranchiseMaintenanceScanService()
        for media_id_to_nudge in sorted(media_ids_to_nudge):
            try:
                maintenance_states_nudged += scan_service.mark_media_due_soon(
                    media_id_to_nudge
                )
            except Exception:
                logger.exception(
                    "Failed to nudge MAL anime franchise maintenance state due soon "
                    "for media_id=%s",
                    media_id_to_nudge,
                )

        logger.info(
            "MAL anime franchise invalidation processed for media_id=%s "
            "canonical_media_id=%s invalidation_reason=%s "
            "changed_relation_types=%s changed_edges=%s "
            "invalidated_canonical_media_ids=%s maintenance_states_nudged=%s "
            "scheduled=%s",
            media_id,
            canonical_media_id,
            invalidation_reason,
            changed_relation_types,
            sorted(changed_edges),
            sorted(invalidated_canonical_media_ids),
            maintenance_states_nudged,
            scheduled,
        )

        return {
            "changed": True,
            "scheduled": scheduled,
            "canonical_media_id": canonical_media_id,
            "invalidation_reason": invalidation_reason,
            "changed_relation_types": changed_relation_types,
            "touched_media_ids": sorted(touched_media_ids),
            "invalidated_canonical_media_ids": sorted(invalidated_canonical_media_ids),
            "missing_payload_media_ids": sorted(missing_payload_media_ids),
            "maintenance_states_nudged": maintenance_states_nudged,
            "old_edges": sorted(old_edges),
            "new_edges": sorted(new_edges),
            "changed_edges": sorted(changed_edges),
        }

    def _extract_invalidation_edges(
        self,
        metadata,
        fallback_media_id,
    ) -> set[tuple[str, str, str]]:
        """Return normalized MAL edges that require strong invalidation."""
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

            if relation_type not in STRONG_INVALIDATION_RELATIONS:
                continue
            if target_media_id in (None, ""):
                continue

            edges.add((source_media_id, str(target_media_id), relation_type))

        return edges

    def _extract_continuity_edges(
        self,
        metadata,
        fallback_media_id,
    ) -> set[tuple[str, str, str]]:
        """Return normalized MAL prequel/sequel edges from anime metadata."""
        return {
            edge
            for edge in self._extract_invalidation_edges(metadata, fallback_media_id)
            if edge[2] in CONTINUITY_INVALIDATION_RELATIONS
        }

    def _media_ids_from_edges(self, *, media_id, edges) -> set[str]:
        """Return source and target media IDs touched by changed relation edges."""
        media_ids = {str(media_id or "").strip()}
        for source_media_id, target_media_id, _relation_type in edges:
            media_ids.add(str(source_media_id or "").strip())
            media_ids.add(str(target_media_id or "").strip())
        media_ids.discard("")
        return media_ids

    def _invalidation_reason(self, changed_relation_types) -> str:
        """Return the strongest cache invalidation reason for changed relations."""
        if CONTINUITY_INVALIDATION_RELATIONS.intersection(changed_relation_types):
            return CONTINUITY_INVALIDATION_REASON
        return FRANCHISE_STRUCTURE_INVALIDATION_REASON
