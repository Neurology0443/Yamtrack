"""Canonical orchestration for rebuilding the persisted anime series view."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_local_series_projection import (
    SERIES_VIEW_PROFILE_KEY,
    AnimeLocalSeriesProjectionService,
)
from app.services.anime_local_series_resolver import AnimeLocalSeriesResolver
from app.services.anime_tracking import bulk_mal_anime_tracked_ids

logger = logging.getLogger(__name__)

SAFE_PARENT_RELATIONS = frozenset({"parent_story", "full_story"})
UNSAFE_CANONICAL_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting", "other", "character"}
)


@dataclass
class AnimeLocalSeriesProjectionRefreshStats:
    """Counters for a canonical projection refresh."""

    canonical_roots_considered: int = 0
    canonical_roots_refreshed: int = 0
    canonical_roots_skipped: int = 0
    groups_resolved: int = 0
    memberships_recorded: int = 0
    memberships_created: int = 0
    memberships_updated: int = 0
    memberships_deleted: int = 0
    errors: int = 0
    dry_run_skips: int = 0


@dataclass(frozen=True)
class _CanonicalCandidate:
    seed_media_id: str
    reason: str
    input_media_ids: tuple[str, ...]
    snapshot: object | None = None


class AnimeLocalSeriesProjectionRefreshService:
    """Single orchestration path for every series-view rebuild trigger."""

    def __init__(
        self,
        *,
        snapshot_service=None,
        resolver=None,
        projection_service=None,
    ):
        """Initialize orchestration dependencies."""
        self.snapshot_service = snapshot_service or AnimeFranchiseSnapshotService()
        self.resolver = resolver or AnimeLocalSeriesResolver()
        self.projection_service = (
            projection_service or AnimeLocalSeriesProjectionService()
        )

    def refresh_for_media_ids(
        self,
        *,
        user,
        media_ids,
        refresh_cache=False,
        dry_run=False,
    ):
        """Rebuild each affected canonical franchise at most once."""
        stats = AnimeLocalSeriesProjectionRefreshStats()
        normalized_ids = sorted(
            {
                str(media_id).strip()
                for media_id in media_ids
                if media_id is not None and str(media_id).strip()
            },
            key=_media_id_key,
        )
        if not normalized_ids:
            return stats

        local_snapshots = {}
        raw_candidates = []
        for media_id in normalized_ids:
            try:
                local_snapshot = self.snapshot_service.build(
                    media_id,
                    refresh_cache=refresh_cache,
                )
            except Exception:
                stats.errors += 1
                stats.canonical_roots_skipped += 1
                logger.exception(
                    "Anime series refresh failed to build input snapshot",
                    extra={"user_id": user.id, "candidate_seed": media_id},
                )
                continue

            local_snapshots[media_id] = local_snapshot
            candidate_seed, reason = self._canonical_seed(local_snapshot)
            raw_candidates.append(
                _CanonicalCandidate(
                    seed_media_id=str(candidate_seed),
                    reason=reason,
                    input_media_ids=(media_id,),
                )
            )

        candidates = {}
        for raw_candidate in raw_candidates:
            canonical_key, reason, reusable_snapshot = self._collapse_candidate(
                raw_candidate,
                local_snapshots,
            )
            current = candidates.get(canonical_key)
            inputs = tuple(
                sorted(
                    {
                        *(current.input_media_ids if current else ()),
                        *raw_candidate.input_media_ids,
                    },
                    key=_media_id_key,
                )
            )
            candidates[canonical_key] = _CanonicalCandidate(
                seed_media_id=canonical_key,
                reason=reason,
                input_media_ids=inputs,
                snapshot=(
                    current.snapshot
                    if current is not None and current.snapshot is not None
                    else reusable_snapshot
                ),
            )

        stats.canonical_roots_considered = len(candidates)
        for candidate in candidates.values():
            snapshot = candidate.snapshot
            if snapshot is None:
                try:
                    snapshot = self.snapshot_service.build(
                        candidate.seed_media_id,
                        refresh_cache=refresh_cache,
                    )
                except Exception:
                    stats.errors += 1
                    stats.canonical_roots_skipped += 1
                    logger.exception(
                        "Anime series refresh skipped failed canonical rebuild",
                        extra={
                            "user_id": user.id,
                            "input_media_ids": candidate.input_media_ids,
                            "candidate_seed": candidate.seed_media_id,
                            "reason": "skipped_canonical_build_failed",
                        },
                    )
                    continue

            scope = self._snapshot_scope(snapshot) | set(candidate.input_media_ids)
            tracked_ids = bulk_mal_anime_tracked_ids(
                user_id=user.id,
                media_ids=scope,
            )
            resolution = self.resolver.resolve(
                snapshot=snapshot,
                tracked_media_ids=tracked_ids,
            )
            stats.groups_resolved += len(resolution.groups)

            if dry_run:
                stats.dry_run_skips += 1
                stats.memberships_recorded += sum(
                    len(group.member_media_ids) for group in resolution.groups
                )
            else:
                persisted = self.projection_service.persist(
                    user=user,
                    source_profile_key=SERIES_VIEW_PROFILE_KEY,
                    resolver_version=resolution.resolver_version,
                    resolution=resolution,
                    scope_media_ids=scope,
                )
                stats.memberships_recorded += persisted.memberships_recorded
                stats.memberships_created += persisted.memberships_created
                stats.memberships_updated += persisted.memberships_updated
                stats.memberships_deleted += persisted.memberships_deleted

            stats.canonical_roots_refreshed += 1
            logger.info(
                "Anime series canonical projection refreshed",
                extra={
                    "user_id": user.id,
                    "input_media_ids": candidate.input_media_ids,
                    "canonical_seed": candidate.seed_media_id,
                    "canonical_root_media_id": snapshot.canonical_root_media_id,
                    "reason": candidate.reason,
                    "snapshot_node_count": len(snapshot.nodes_by_media_id),
                    "scope_count": len(scope),
                    "tracked_count": len(tracked_ids),
                    "group_count": len(resolution.groups),
                    "memberships_recorded": sum(
                        len(group.member_media_ids) for group in resolution.groups
                    ),
                    "dry_run": dry_run,
                },
            )
        return stats

    def refresh_for_franchise_seed(self, *, user, seed_media_id, **kwargs):
        """Refresh one affected media ID."""
        return self.refresh_for_media_ids(
            user=user,
            media_ids=[seed_media_id],
            **kwargs,
        )

    def _collapse_candidate(self, candidate, local_snapshots):
        seed = candidate.seed_media_id
        reason = candidate.reason
        visited = set()
        while seed in local_snapshots and seed not in visited:
            visited.add(seed)
            snapshot = local_snapshots[seed]
            next_seed, next_reason = self._canonical_seed(snapshot)
            if next_seed == seed:
                return seed, reason, snapshot
            if next_reason == "already_canonical":
                return str(next_seed), reason, snapshot
            seed = str(next_seed)
            reason = next_reason
        return seed, reason, None

    @staticmethod
    def _canonical_seed(snapshot):
        root_id = str(snapshot.root_node.media_id)
        safe_parents = sorted(
            {
                str(relation.target_media_id)
                for relation in snapshot.root_node.relations
                if relation.relation_type in SAFE_PARENT_RELATIONS
                and relation.relation_type not in UNSAFE_CANONICAL_RELATIONS
            },
            key=_media_id_key,
        )
        if safe_parents:
            return safe_parents[0], "parent_story_promoted"

        side_story_parents = sorted(
            {
                str(relation.source_media_id)
                for relation in snapshot.all_normalized_relations
                if relation.target_media_id == root_id
                and relation.relation_type == "side_story"
            },
            key=_media_id_key,
        )
        if side_story_parents:
            return side_story_parents[0], "side_story_parent_promoted"

        canonical_id = str(snapshot.canonical_root_media_id)
        if canonical_id != root_id:
            return canonical_id, "already_canonical"
        return root_id, "already_canonical"

    @staticmethod
    def _snapshot_scope(snapshot):
        scope = set(snapshot.nodes_by_media_id)
        scope.update(node.media_id for node in snapshot.continuity_component)
        scope.update(node.media_id for node in snapshot.series_line)
        scope.update(node.media_id for node in snapshot.direct_anchors)
        for field_name in (
            "direct_candidates",
            "promoted_continuity_candidates",
            "no_series_line_secondary_candidates",
            "root_story_parent_candidates",
            "all_normalized_relations",
        ):
            for relation in getattr(snapshot, field_name, ()) or ():
                scope.add(str(relation.source_media_id))
                scope.add(str(relation.target_media_id))
        return scope


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
