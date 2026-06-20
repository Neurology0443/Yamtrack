"""Project reusable branch context facts for Anime Series View."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.anime_franchise_ui.assembler import UiCandidateAssembler

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


BRANCH_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting"}
)


@dataclass(frozen=True)
class AnimeLocalBranchContext:
    """One UI-projected parent-to-branch relationship."""

    branch_media_id: str
    parent_media_id: str
    relation_type: str


class AnimeLocalSeriesBranchContextProjector:
    """Reuse franchise UI candidates to orient local Series View contexts."""

    def __init__(self, candidate_assembler=None):
        """Create the projector with an optional reusable candidate assembler."""
        self.candidate_assembler = candidate_assembler or UiCandidateAssembler()

    def project(
        self,
        snapshot: AnimeFranchiseSnapshot,
    ) -> list[AnimeLocalBranchContext]:
        """Return only unambiguous branch facts exposed by UI candidates."""
        contexts = []
        for candidate in self.candidate_assembler.build(snapshot):
            candidate_contexts = {
                (
                    str(origin.get("source_media_id")),
                    str(origin.get("relation_type")),
                )
                for origin in candidate.metadata.get("origins", [])
                if origin.get("relation_type") in BRANCH_RELATIONS
                and (
                    origin.get("is_from_series_line")
                    or origin.get("is_from_root_node")
                )
                and origin.get("source_media_id") is not None
                and str(origin.get("source_media_id")) != str(candidate.media_id)
            }
            if len(candidate_contexts) != 1:
                continue

            parent_media_id, relation_type = next(iter(candidate_contexts))
            contexts.append(
                AnimeLocalBranchContext(
                    branch_media_id=str(candidate.media_id),
                    parent_media_id=parent_media_id,
                    relation_type=relation_type,
                )
            )

        return sorted(
            contexts,
            key=lambda context: (
                _media_id_key(context.branch_media_id),
                _media_id_key(context.parent_media_id),
                context.relation_type,
            ),
        )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
