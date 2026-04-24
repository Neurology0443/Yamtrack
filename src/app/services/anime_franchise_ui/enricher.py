"""Targeted classification enrichment for light UI candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder

if TYPE_CHECKING:
    from .candidates import UiCandidate
    from .rule_types import RuleContext


class UiCandidateClassificationEnricher:
    """Hydrate only the metadata required for classification-sensitive rules."""

    def __init__(self, graph_builder: AnimeFranchiseGraphBuilder | None = None):
        self.graph_builder = graph_builder or AnimeFranchiseGraphBuilder()

    def enrich(self, candidates: list[UiCandidate], context: RuleContext) -> None:
        for candidate in candidates:
            if not self._needs_classification_metadata(candidate):
                continue
            node = self.graph_builder.ensure_classification_node(candidate.media_id)
            candidate.media_type = node.media_type
            candidate.runtime_minutes = node.runtime_minutes
            candidate.start_date = node.start_date
            if not candidate.image or candidate.image == settings.IMG_NONE:
                candidate.image = node.image
            if not candidate.title or candidate.title == candidate.media_id:
                candidate.title = node.title
            if not candidate.source:
                candidate.source = node.source
            candidate.metadata["classification_enriched"] = True
            candidate.metadata["classification_fields"] = [
                "media_type",
                "runtime_minutes",
                "start_date",
            ]
            calls = context.state.setdefault("classification_enrichment_calls", [])
            calls.append(candidate.media_id)

    @staticmethod
    def _needs_classification_metadata(candidate: UiCandidate) -> bool:
        if not candidate.is_light:
            return False
        relation_types = set(candidate.relation_types)
        if relation_types & {"alternative_version", "alternative_setting"}:
            return False
        if relation_types & {"spin_off", "side_story", "summary", "full_story"}:
            return True
        if relation_types & {"prequel", "sequel"}:
            return (
                candidate.metadata.get("is_continuity_enrichment_candidate") is True
                or candidate.metadata.get("is_promoted_continuity") is True
                or candidate.metadata.get("is_promoted_continuity_entrypoint") is True
                or candidate.section_key == "continuity_extras"
            )
        return False
