"""Baseline fact enrichment shared by downstream placement/refinement packs."""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import Rule, RulePack


RELATED_RELATIONS = {
    "spin_off",
    "parent_story",
    "alternative_setting",
    "alternative_version",
    "character",
}


def _set_relation_facts(candidate, _context) -> None:
    rels = set(candidate.relation_types)
    origins = candidate.metadata.get("origins", [])
    candidate.metadata["relation_facts"] = {
        "only_other": bool(rels) and rels == {"other"},
        "has_continuity": bool({"prequel", "sequel"} & rels),
        "has_specials": bool({"side_story", "summary", "full_story"} & rels),
        "has_related": bool(RELATED_RELATIONS & rels),
        "has_series_origin": any(origin.get("is_from_series_line") for origin in origins),
        "has_root_origin": any(origin.get("is_from_root_node") for origin in origins),
    }


BaseFactsRules = RulePack(
    key="base_facts",
    rules=(
        Rule(
            key="relation_facts",
            when=lambda _candidate, _context: True,
            actions=(_set_relation_facts,),
        ),
    ),
)
