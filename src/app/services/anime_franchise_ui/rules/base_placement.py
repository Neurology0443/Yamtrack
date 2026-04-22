"""Base placement rules for coarse section declarations and defaults."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import ensure_section, place_in
from app.services.anime_franchise_ui.predicates import run_once
from app.services.anime_franchise_ui.rule_types import Rule, RulePack


def _no_section(candidate, _context) -> bool:
    return candidate.section_key is None


BasePlacementRules = RulePack(
    key="base_placement",
    rules=(
        Rule(
            key="declare_sections",
            when=run_once("sections_declared"),
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
                    key="spin_offs",
                    title="Spin Offs",
                    order=40,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
                ensure_section(
                    key="alternatives",
                    title="Alternatives",
                    order=50,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
                ensure_section(
                    key="related_series",
                    title="Related Series",
                    order=60,
                    hidden_if_empty=True,
                    metadata={"visible_in_ui": True},
                ),
            ),
        ),
        Rule(
            key="fallback_related",
            when=_no_section,
            actions=(place_in("related_series"),),
        ),
    ),
)
