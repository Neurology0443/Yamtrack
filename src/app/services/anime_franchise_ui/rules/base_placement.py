"""Base placement rules for coarse section declarations and defaults."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import ensure_section, place_in
from app.services.anime_franchise_ui.predicates import always
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

BasePlacementRules = RulePack(
    key="base_placement",
    rules=(
        Rule(
            key="declare_core_sections",
            when=always(),
            actions=(
                ensure_section(
                    key="ignored",
                    title="Ignored",
                    order=10,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": False},
                ),
                ensure_section(
                    key="continuity_extras",
                    title="Main Story Extras",
                    order=20,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
                ensure_section(
                    key="specials",
                    title="Specials",
                    order=30,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
                ensure_section(
                    key="related_series",
                    title="Related Series",
                    order=40,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
            ),
        ),
        Rule(
            key="default_place_in_related_series",
            when=always(),
            actions=(place_in("related_series"),),
        ),
    ),
)
