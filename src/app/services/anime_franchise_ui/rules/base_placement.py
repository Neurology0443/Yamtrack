"""Base placement rules for generic secondary candidates."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import ensure_section, place_in
from app.services.anime_franchise_ui.predicates import always
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

BasePlacementRules = RulePack(
    key="base_placement",
    rules=(
        Rule(
            key="default_other_entries_section",
            when=always(),
            actions=(
                ensure_section(
                    key="other_entries",
                    title="Other Entries",
                    order=1000,
                    hidden_if_empty=True,
                ),
                place_in("other_entries"),
            ),
        ),
    ),
)
