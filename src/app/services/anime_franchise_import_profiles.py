"""Import profiles powered by AnimeFranchiseSnapshot."""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


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

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:
        ids = {
            node.media_id
            for node in snapshot.continuity_component
            if node.media_type not in self.ignored_media_types
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
        {"spin_off", "alternative_version", "side_story", "parent_story"}
    )

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
