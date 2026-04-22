"""Refine coarse secondary-section placement after `relation_rules` classification."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import place_in, set_candidate_metadata
from app.services.anime_franchise_ui.rule_types import Rule, RulePack


def _is_related_series_candidate(candidate, _context) -> bool:
    return candidate.section_key == "related_series"


def _is_specials_tv_side_story(candidate, _context) -> bool:
    return (
        candidate.section_key == "specials"
        and "side_story" in candidate.relation_types
        and candidate.media_type == "tv"
    )


def _is_short_side_story_special(candidate, _context) -> bool:
    return (
        candidate.section_key == "specials"
        and "side_story" in candidate.relation_types
        and candidate.runtime_minutes is not None
        and candidate.runtime_minutes < 15
    )


def _is_long_tv_spin_off_related(candidate, context) -> bool:
    return (
        _is_related_series_candidate(candidate, context)
        and "spin_off" in candidate.relation_types
        and candidate.media_type == "tv"
        and candidate.runtime_minutes is not None
    )


def _is_alternative_version_related(candidate, context) -> bool:
    return (
        _is_related_series_candidate(candidate, context)
        and "alternative_version" in candidate.relation_types
    )


def _is_alternative_setting_related(candidate, context) -> bool:
    return (
        _is_related_series_candidate(candidate, context)
        and "alternative_setting" in candidate.relation_types
    )


SecondaryRefinementRules = RulePack(
    key="secondary_refinement_rules",
    rules=(
        Rule(
            key="tv_side_story_from_specials_to_related_series",
            when=_is_specials_tv_side_story,
            actions=(place_in("related_series"),),
        ),
        Rule(
            key="short_side_story_from_specials_to_related_series",
            when=_is_short_side_story_special,
            actions=(place_in("related_series"),),
        ),
        Rule(
            key="alternative_version_to_alternatives",
            when=_is_alternative_version_related,
            actions=(
                place_in("alternatives"),
                set_candidate_metadata("section_sort_rank", 0),
            ),
        ),
        Rule(
            key="alternative_setting_to_alternatives",
            when=_is_alternative_setting_related,
            actions=(
                place_in("alternatives"),
                set_candidate_metadata("section_sort_rank", 1),
            ),
        ),
        Rule(
            key="long_tv_spinoff_to_spin_offs",
            when=_is_long_tv_spin_off_related,
            actions=(place_in("spin_offs"),),
        ),
    ),
)
