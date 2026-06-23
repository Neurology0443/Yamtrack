"""Stable business rules shared by Anime Series View projections."""

SERIES_VIEW_CONTINUITY_RELATIONS = frozenset({"prequel", "sequel"})
SERIES_VIEW_GROUPABLE_RELATIONS = frozenset(
    {
        "prequel",
        "sequel",
        "parent_story",
        "full_story",
        "side_story",
        "spin_off",
    }
)

SERIES_VIEW_ROOT_MEDIA_TYPES = frozenset({"tv", "ona", "movie", "ova"})

SERIES_VIEW_STRONG_REROOT_RELATIONS = frozenset(
    {
        "parent_story",
        "full_story",
    }
)

SERIES_VIEW_REROOT_RELATION_PRIORITY = {
    "full_story": 0,
    "parent_story": 0,
    "side_story": 2,
    "spin_off": 2,
    "prequel": 3,
    "sequel": 3,
}
