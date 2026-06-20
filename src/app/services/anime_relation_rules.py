"""Shared normalized relation rules for anime franchise projections."""

GROUPABLE_RELATIONS = frozenset(
    {
        "prequel",
        "sequel",
        "side_story",
        "parent_story",
        "summary",
        "full_story",
    }
)
BRANCH_BOUNDARY_RELATIONS = frozenset(
    {"spin_off", "alternative_version", "alternative_setting"}
)
PROJECTION_RELEVANT_RELATIONS = (
    GROUPABLE_RELATIONS | BRANCH_BOUNDARY_RELATIONS
)
CONTINUITY_RELATIONS = frozenset({"prequel", "sequel"})
