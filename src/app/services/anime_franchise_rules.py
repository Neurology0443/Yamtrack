"""Section rules for MAL anime franchise grouping."""

from __future__ import annotations

from app.services.anime_franchise_types import (
    AnimeFranchiseCandidate,
    AnimeFranchiseSectionRule,
)


def _ignored_other(candidate: AnimeFranchiseCandidate) -> bool:
    return candidate.relation_type == "other"


SECTION_RULES = [
    AnimeFranchiseSectionRule(
        key="ignored",
        title="Ignored",
        visible_in_ui=False,
        priority=10,
        include_media_types=frozenset({"cm", "pv"}),
        sort_mode="linked_then_date",
    ),
    AnimeFranchiseSectionRule(
        key="ignored",
        title="Ignored",
        visible_in_ui=False,
        priority=11,
        sort_mode="linked_then_date",
        predicate=_ignored_other,
    ),
    AnimeFranchiseSectionRule(
        key="continuity_extras",
        title="Main Story Extras",
        visible_in_ui=True,
        priority=20,
        include_relation_types=frozenset({"prequel", "sequel"}),
        include_media_types=frozenset({"movie", "ova", "ona", "special", "tv_special"}),
        exclude_media_types=frozenset({"tv", "cm", "pv"}),
        direct_from_series_line_only=True,
        allow_indirect_candidates=False,
        sort_mode="continuity_extras",
        hidden_if_empty=True,
    ),
    AnimeFranchiseSectionRule(
        key="specials",
        title="Specials",
        visible_in_ui=True,
        priority=30,
        include_relation_types=frozenset({"side_story", "summary", "full_story"}),
        include_media_types=frozenset({"ova", "movie", "special", "tv_special"}),
        exclude_media_types=frozenset({"tv", "ona", "cm", "pv"}),
        direct_from_series_line_only=True,
        allow_indirect_candidates=False,
        sort_mode="linked_then_date",
        hidden_if_empty=True,
    ),
    AnimeFranchiseSectionRule(
        key="related_series",
        title="Related Series",
        visible_in_ui=True,
        priority=40,
        include_relation_types=frozenset(
            {
                "spin_off",
                "parent_story",
                "alternative_setting",
                "alternative_version",
                "character",
            }
        ),
        include_media_types=frozenset(
            {"tv", "movie", "ova", "ona", "special", "tv_special"}
        ),
        exclude_media_types=frozenset({"cm", "pv"}),
        direct_from_series_line_only=True,
        allow_indirect_candidates=False,
        sort_mode="linked_then_date",
        hidden_if_empty=True,
    ),
]


def get_section_rules() -> list[AnimeFranchiseSectionRule]:
    """Return sorted section rules evaluated by priority."""
    return sorted(SECTION_RULES, key=lambda rule: rule.priority)
