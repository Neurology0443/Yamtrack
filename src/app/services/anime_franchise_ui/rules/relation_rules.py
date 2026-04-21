"""Coarse relation-driven placement refinements."""

from __future__ import annotations
from app.services.anime_franchise_ui.actions import place_in
from app.services.anime_franchise_ui.predicates import relation_type_in, relation_type_is
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

RelationRules = RulePack(
    key="relation_rules",
    rules=(
        Rule(
            key="ignore_relation_other",
            when=relation_type_is("other"),
            actions=(place_in("ignored"),),
        ),
        Rule(
            key="place_continuity_extras_by_relation",
            when=relation_type_in({"prequel", "sequel"}),
            actions=(place_in("continuity_extras"),),
        ),
        Rule(
            key="place_specials_by_relation",
            when=relation_type_in({"side_story", "summary", "full_story"}),
            actions=(place_in("specials"),),
        ),
        Rule(
            key="place_related_series_by_relation",
            when=relation_type_in(
                {
                    "spin_off",
                    "parent_story",
                    "alternative_setting",
                    "alternative_version",
                    "character",
                },
            ),
            actions=(place_in("related_series"),),
        ),
    ),
)
