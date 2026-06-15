"""Coarse relation-driven placement refinements."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import place_in
from app.services.anime_franchise_ui.rule_types import Rule, RulePack


def _facts(candidate) -> dict:
    return candidate.metadata.get("relation_facts", {})


def _only_other(candidate, _context) -> bool:
    return bool(_facts(candidate).get("only_other"))


def _continuity(candidate, _context) -> bool:
    return bool(_facts(candidate).get("has_continuity"))


def _specials(candidate, _context) -> bool:
    if candidate.metadata.get("is_root_story_parent"):
        return False
    return bool(_facts(candidate).get("has_specials"))


def _root_story_parent(candidate, _context) -> bool:
    return bool(candidate.metadata.get("is_root_story_parent"))


def _related(candidate, _context) -> bool:
    facts = _facts(candidate)
    return bool(facts.get("has_related")) and not (
        facts.get("has_continuity") or facts.get("has_specials")
    )


RelationRules = RulePack(
    key="relation_rules",
    rules=(
        Rule(
            key="ignore_only_other",
            when=_only_other,
            actions=(place_in("ignored"),),
        ),
        Rule(
            key="continuity_by_relations",
            when=_continuity,
            actions=(place_in("continuity_extras"),),
        ),
        Rule(
            key="root_story_parent_to_related_series",
            when=_root_story_parent,
            actions=(place_in("related_series"),),
        ),
        Rule(
            key="specials_by_relations",
            when=_specials,
            actions=(place_in("specials"),),
        ),
        Rule(
            key="related_by_relations",
            when=_related,
            actions=(place_in("related_series"),),
        ),
    ),
)
