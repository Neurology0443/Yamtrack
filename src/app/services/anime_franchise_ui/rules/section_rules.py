"""Section metadata stabilization for coarse UI compatibility."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import (
    set_section_hidden_if_empty,
    set_section_order,
    set_section_title,
)
from app.services.anime_franchise_ui.predicates import always
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

SectionRules = RulePack(
    key="section_rules",
    rules=(
        Rule(
            key="set_ignored_section_metadata",
            when=always(),
            actions=(
                set_section_title(key="ignored", title="Ignored"),
                set_section_order(key="ignored", order=10),
                set_section_hidden_if_empty(key="ignored", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="set_continuity_section_metadata",
            when=always(),
            actions=(
                set_section_title(key="continuity_extras", title="Main Story Extras"),
                set_section_order(key="continuity_extras", order=20),
                set_section_hidden_if_empty(key="continuity_extras", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="set_specials_section_metadata",
            when=always(),
            actions=(
                set_section_title(key="specials", title="Specials"),
                set_section_order(key="specials", order=30),
                set_section_hidden_if_empty(key="specials", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="set_related_series_metadata",
            when=always(),
            actions=(
                set_section_title(key="related_series", title="Related Series"),
                set_section_order(key="related_series", order=40),
                set_section_hidden_if_empty(key="related_series", hidden_if_empty=True),
            ),
        ),
    ),
)
