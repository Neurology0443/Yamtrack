"""Import profiles powered by AnimeFranchiseSnapshot."""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import AnimeNode


class SeedMode(StrEnum):
    """Seed selection modes available for import profiles."""

    ALL_LIBRARY = "all_library"
    CANONICAL_ONLY = "canonical_only"


@dataclass(frozen=True)
class ProfileSelection:
    """Selected ids and fingerprint payload for a profile run."""

    media_ids: set[str]
    fingerprint_payload: dict


class BaseImportProfile:
    key = "base"
    seed_mode = SeedMode.ALL_LIBRARY
    continuity_mode = "none"
    satellites_mode = "none"
    component_root_mode = "canonical_component_root"
    include_relation_types: frozenset[str] = frozenset()

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:  # pragma: no cover
        raise NotImplementedError

    def component_root_media_id(self, snapshot: AnimeFranchiseSnapshot) -> str:
        """Return canonical continuity component root for persisted scan state.

        This root is global to the continuity component and profile-independent.
        """
        return snapshot.canonical_root_media_id

    def detail_cache_warm_media_ids(
        self,
        snapshot: AnimeFranchiseSnapshot,
        created_ids: set[str],
    ) -> set[str]:
        """Return created media IDs that should receive a detail/scoped cache warm.

        This method is intentionally pure.

        It must not:
        - schedule Celery tasks;
        - touch Redis/cache;
        - call transaction.on_commit;
        - mutate database state;
        - mutate import stats.
        """
        return set()

    def is_seed_eligible(
        self,
        *,
        seed_mal_id: str,
        known_canonical_root: str | None,
    ) -> bool:
        if self.seed_mode == SeedMode.ALL_LIBRARY:
            return True
        if self.seed_mode == SeedMode.CANONICAL_ONLY:
            return known_canonical_root == seed_mal_id
        msg = f"Unsupported seed_mode '{self.seed_mode}' for profile '{self.key}'."
        raise ValueError(msg)


class ContinuityImportProfile(BaseImportProfile):
    key = "continuity"
    continuity_mode = "transitive"
    ignored_media_types = {"cm", "pv"}
    min_runtime_minutes = 15

    def detail_cache_warm_media_ids(
        self,
        snapshot: AnimeFranchiseSnapshot,
        created_ids: set[str],
    ) -> set[str]:
        return set()

    def is_runtime_eligible(self, node: AnimeNode) -> bool:
        runtime_minutes = node.runtime_minutes
        if runtime_minutes is None:
            return True
        return runtime_minutes > self.min_runtime_minutes

    def _summary_target_ids(self, snapshot: AnimeFranchiseSnapshot) -> set[str]:
        return {
            relation.target_media_id
            for relation in snapshot.all_normalized_relations
            if relation.relation_type == "summary"
        }

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:
        summary_target_ids = self._summary_target_ids(snapshot)
        ids = {
            node.media_id
            for node in snapshot.continuity_component
            if node.media_type not in self.ignored_media_types
            and self.is_runtime_eligible(node)
            and node.media_id not in summary_target_ids
        }
        payload = {
            "continuity_ids": sorted(ids),
            "media_types": sorted(
                {
                    snapshot.nodes_by_media_id[media_id].media_type
                    for media_id in ids
                }
            ),
        }
        return ProfileSelection(media_ids=ids, fingerprint_payload=payload)


class SatellitesImportProfile(BaseImportProfile):
    key = "satellites"
    seed_mode = SeedMode.CANONICAL_ONLY
    satellites_mode = "direct_only"
    ignored_media_types = {"cm", "pv"}
    include_relation_types = frozenset(
        {"spin_off", "alternative_version", "side_story"}
    )
    min_runtime_minutes = 15
    single_episode_max_runtime_minutes = 30
    local_continuity_relation_types = frozenset({"prequel", "sequel"})

    def detail_cache_warm_media_ids(
        self,
        snapshot: AnimeFranchiseSnapshot,
        created_ids: set[str],
    ) -> set[str]:
        return {str(media_id) for media_id in created_ids}

    def is_runtime_episode_eligible(
        self,
        snapshot: AnimeFranchiseSnapshot,
        target_node: AnimeNode,
    ) -> bool:
        runtime_minutes = target_node.runtime_minutes

        if target_node.media_type == "tv_special":
            if runtime_minutes is None:
                return False
            return runtime_minutes > self.min_runtime_minutes

        if runtime_minutes is None:
            return False

        if runtime_minutes < self.min_runtime_minutes:
            return False

        if self.is_short_single_episode(target_node):
            return self.is_clean_local_continuity_branch(snapshot, target_node)

        return True

    def is_short_single_episode(self, target_node: AnimeNode) -> bool:
        return (
            target_node.episode_count == 1
            and target_node.runtime_minutes is not None
            and target_node.runtime_minutes <= self.single_episode_max_runtime_minutes
        )

    def is_clean_local_continuity_branch(
        self,
        snapshot: AnimeFranchiseSnapshot,
        target_node: AnimeNode,
    ) -> bool:
        component, is_complete = self.local_continuity_component(
            snapshot,
            target_node.media_id,
        )

        if not is_complete:
            return False

        for node in component:
            if node.runtime_minutes is None:
                return False
            if node.runtime_minutes < self.min_runtime_minutes:
                return False
        return True

    def local_continuity_component(
        self,
        snapshot: AnimeFranchiseSnapshot,
        root_media_id: str,
    ) -> tuple[list[AnimeNode], bool]:
        queue = [str(root_media_id)]
        seen = set()
        component = []
        is_complete = True

        while queue:
            media_id = queue.pop(0)
            if media_id in seen:
                continue

            seen.add(media_id)

            node = snapshot.nodes_by_media_id.get(media_id)
            if node is None:
                is_complete = False
                continue

            component.append(node)

            for relation in snapshot.all_normalized_relations:
                if relation.relation_type not in self.local_continuity_relation_types:
                    continue

                if relation.source_media_id == media_id:
                    if relation.target_media_id not in seen:
                        queue.append(relation.target_media_id)

                elif relation.target_media_id == media_id:
                    if relation.source_media_id not in seen:
                        queue.append(relation.source_media_id)

        return component, is_complete

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:
        continuity_ids = {
            node.media_id
            for node in snapshot.continuity_component
        }
        selected = []
        for relation in snapshot.direct_candidates:
            if (
                self.include_relation_types
                and relation.relation_type not in self.include_relation_types
            ):
                continue
            target_node = snapshot.nodes_by_media_id[relation.target_media_id]
            if target_node.media_type in self.ignored_media_types:
                continue
            if relation.target_media_id in continuity_ids:
                continue
            if not self.is_runtime_episode_eligible(snapshot, target_node):
                continue
            selected.append(relation)

        ids = {relation.target_media_id for relation in selected}
        payload = {
            "satellite_ids": sorted(ids),
            "relations": sorted(
                [
                    {
                        "source_id": relation.source_media_id,
                        "target_id": relation.target_media_id,
                        "relation_type": relation.relation_type,
                        "media_type": snapshot.nodes_by_media_id[relation.target_media_id].media_type,
                    }
                    for relation in selected
                ],
                key=lambda row: (row["source_id"], row["target_id"], row["relation_type"]),
            ),
        }
        return ProfileSelection(media_ids=ids, fingerprint_payload=payload)


class CompleteImportProfile(BaseImportProfile):
    key = "complete"
    continuity_mode = "transitive"
    satellites_mode = "direct_only"

    def __init__(self):
        self.continuity = ContinuityImportProfile()
        self.satellites = SatellitesImportProfile()

    def detail_cache_warm_media_ids(
        self,
        snapshot: AnimeFranchiseSnapshot,
        created_ids: set[str],
    ) -> set[str]:
        satellite_ids = {
            str(media_id)
            for media_id in self.satellites.select(snapshot).media_ids
        }
        return {
            str(media_id)
            for media_id in created_ids
            if str(media_id) in satellite_ids
        }

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:
        continuity = self.continuity.select(snapshot)
        satellites = self.satellites.select(snapshot)
        ids = set(continuity.media_ids) | set(satellites.media_ids)
        payload = {
            "continuity": continuity.fingerprint_payload,
            "satellites": satellites.fingerprint_payload,
            "union_ids": sorted(ids),
        }
        return ProfileSelection(media_ids=ids, fingerprint_payload=payload)


def get_import_profile(profile_key: str) -> BaseImportProfile:
    profiles = {
        "continuity": ContinuityImportProfile,
        "satellites": SatellitesImportProfile,
        "complete": CompleteImportProfile,
    }
    if profile_key not in profiles:
        msg = f"Unsupported profile '{profile_key}'"
        raise ValueError(msg)
    return profiles[profile_key]()
