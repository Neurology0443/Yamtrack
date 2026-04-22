"""Default ordered preset for anime franchise UI rule pipeline."""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import RulePack
from app.services.anime_franchise_ui.rules import (
    AnchorRules,
    BaseFactsRules,
    BasePlacementRules,
    FormatRules,
    RelatedRefinementRules,
    RelationRules,
    SectionRules,
)

DefaultUiPreset: tuple[RulePack, ...] = (
    BaseFactsRules,
    BasePlacementRules,
    RelationRules,
    RelatedRefinementRules,
    AnchorRules,
    FormatRules,
    SectionRules,
)
