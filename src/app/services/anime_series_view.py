"""Read-only assembly of Anime Series View from persisted memberships."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Anime, AnimeSeriesViewMembership, MediaTypes, Sources
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)
from app.services.anime_series_view_projection_persistence import (
    SERIES_VIEW_PROFILE_KEY,
)

BRANCH_LABELS = {
    "spin_off": "Spin Off",
    "alternative_version": "Alternative Version",
    "alternative_setting": "Alternative Setting",
}


@dataclass
class AnimeSeriesViewGroup:
    """Template-ready group assembled from local media entries."""

    root_media_id: str
    display_media_id: str
    group_kind: str
    entries: list = field(default_factory=list)
    context_parent_media_id: str | None = None
    context_relation_type: str | None = None
    context_parent_title: str = ""

    @property
    def display_entry(self):
        """Return the persisted display representative with local fallbacks."""
        for entry in self.entries:
            if str(entry.item.media_id) == self.display_media_id:
                return entry
        for entry in self.entries:
            if str(entry.item.media_id) == self.root_media_id:
                return entry
        return self.entries[0]

    @property
    def display_title(self):
        """Return the title shown on the group card."""
        return self.display_entry.item.title

    @property
    def branch_subtitle(self):
        """Return a supported branch label with an optional local parent title."""
        label = BRANCH_LABELS.get(self.context_relation_type, "")
        if not label:
            return ""
        if self.context_parent_title:
            return f"{label} • {self.context_parent_title}"
        return label


def build_anime_series_view(*, media_entries, user_id):
    """Group filtered entries using the DB read model, with singleton fallback."""
    entries = list(media_entries)
    media_ids = [str(entry.item.media_id) for entry in entries]
    memberships = AnimeSeriesViewMembership.objects.filter(
        user_id=user_id,
        source_profile_key=SERIES_VIEW_PROFILE_KEY,
        projection_version=AnimeSeriesViewProjectionBuilder.projection_version,
        media_id__in=media_ids,
    )
    membership_by_media_id = {
        membership.media_id: membership for membership in memberships
    }

    groups = {}
    group_order = []
    for entry in entries:
        media_id = str(entry.item.media_id)
        membership = membership_by_media_id.get(media_id)
        if membership is None:
            key = ("singleton", media_id)
            values = {
                "root_media_id": media_id,
                "display_media_id": media_id,
                "group_kind": "singleton",
            }
        else:
            key = (membership.projection_version, membership.root_media_id)
            values = {
                "root_media_id": membership.root_media_id,
                "display_media_id": membership.display_media_id,
                "group_kind": membership.group_kind,
                "context_parent_media_id": membership.context_parent_media_id,
                "context_relation_type": membership.context_relation_type,
            }
        if key not in groups:
            groups[key] = AnimeSeriesViewGroup(**values)
            group_order.append(key)
        groups[key].entries.append(entry)

    resolved_groups = [groups[key] for key in group_order]
    parent_ids = {
        group.context_parent_media_id
        for group in resolved_groups
        if group.context_parent_media_id
    }
    parent_titles = dict(
        Anime.objects.filter(
            user_id=user_id,
            item__media_id__in=parent_ids,
            item__source=Sources.MAL.value,
            item__media_type=MediaTypes.ANIME.value,
        ).values_list("item__media_id", "item__title")
    )
    for group in resolved_groups:
        group.context_parent_title = parent_titles.get(
            group.context_parent_media_id,
            "",
        )
    return resolved_groups
