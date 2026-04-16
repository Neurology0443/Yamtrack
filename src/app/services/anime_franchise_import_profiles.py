"""Import profiles powered by AnimeFranchiseSnapshot."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


@dataclass(frozen=True)
class ProfileSelection:
    """Selected ids and fingerprint payload for a profile run."""

    media_ids: set[str]
    fingerprint_payload: dict


class BaseImportProfile:
    key = "base"

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:  # pragma: no cover
        raise NotImplementedError


class ContinuityImportProfile(BaseImportProfile):
    key = "continuity"
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
    ignored_media_types = {"cm", "pv"}

    def select(self, snapshot: AnimeFranchiseSnapshot) -> ProfileSelection:
        continuity_ids = {
            node.media_id
            for node in snapshot.continuity_component
        }
        selected = []
        for relation in snapshot.direct_candidates:
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
