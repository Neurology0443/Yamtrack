"""Simple franchise-root projection rules for Anime Series View."""

PROJECTION_VERSION = "franchise_root_v1"
GROUP_KIND_FRANCHISE = "franchise"
GROUP_KIND_SINGLETON = "singleton"


def resolve_series_line_root(snapshot):
    """Return the first canonical series-line node, when one exists."""
    if snapshot.series_line:
        return snapshot.series_line[0]
    return None
