"""Section metadata stabilization for coarse UI compatibility."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import (
    set_section_hidden_if_empty,
    set_section_order,
    set_section_title,
)
from app.services.anime_franchise_ui.predicates import run_once
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

SectionRules = RulePack(
    key="section_rules",
    rules=(
        Rule(
            key="meta_ignored",
            when=run_once("meta_ignored"),
            actions=(
                set_section_title(key="ignored", title="Ignored"),
                set_section_order(key="ignored", order=10),
                set_section_hidden_if_empty(key="ignored", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="meta_continuity",
            when=run_once("meta_continuity"),
            actions=(
                set_section_title(key="continuity_extras", title="Main Story Extras"),
                set_section_order(key="continuity_extras", order=20),
                set_section_hidden_if_empty(key="continuity_extras", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="meta_specials",
            when=run_once("meta_specials"),
            actions=(
                set_section_title(key="specials", title="Specials"),
                set_section_order(key="specials", order=30),
                set_section_hidden_if_empty(key="specials", hidden_if_empty=True),
            ),
        ),
        Rule(
            key="meta_related",
            when=run_once("meta_related"),
            actions=(
                set_section_title(key="related_series", title="Related Series"),
                set_section_order(key="related_series", order=40),
                set_section_hidden_if_empty(key="related_series", hidden_if_empty=True),
            ),
        ),
    ),
)
