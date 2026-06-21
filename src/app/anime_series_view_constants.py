"""Stable constants shared by Anime Series View models and services."""

PROJECTION_VERSION = "franchise_root_v2"

GROUP_KIND_FRANCHISE = "franchise"
GROUP_KIND_SINGLETON = "singleton"

REFRESH_MODE = "refresh"
DELETE_MODE = "delete"
REFRESH_MODES = frozenset({REFRESH_MODE, DELETE_MODE})
