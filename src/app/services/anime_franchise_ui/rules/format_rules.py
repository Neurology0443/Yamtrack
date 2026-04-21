"""Coarse format filters used by section placement compatibility."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import place_in
from app.services.anime_franchise_ui.predicates import media_type_in
from app.services.anime_franchise_ui.rule_types import Rule, RulePack

FormatRules = RulePack(
    key="format_rules",
    rules=(
        Rule(
            key="ignore_cm_pv",
            when=media_type_in({"cm", "pv"}),
            actions=(place_in("ignored"),),
        ),
        Rule(
            key="continuity_extras_exclude_tv_cm_pv",
            when=lambda candidate, _context: (
                candidate.section_key == "continuity_extras"
                and candidate.media_type in {"tv", "cm", "pv"}
            ),
            actions=(place_in("ignored"),),
        ),
        Rule(
            key="specials_require_specific_formats",
            when=lambda candidate, _context: (
                candidate.section_key == "specials"
                and candidate.media_type not in {"ova", "movie", "special", "tv_special"}
            ),
            actions=(place_in("ignored"),),
        ),
    ),
)
