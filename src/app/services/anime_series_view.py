"""Read-only assembly of Anime Series View from persisted memberships."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.urls import reverse
from django.utils.text import slugify

from app.models import AnimeSeriesViewMembership, MediaTypes, Sources
from app.services.anime_series_view_projection import (
    AnimeSeriesViewProjectionBuilder,
)
from app.services.anime_series_view_projection_persistence import (
    SERIES_VIEW_PROFILE_KEY,
)

if TYPE_CHECKING:
    from datetime import date

BRANCH_LABELS = {
    "spin_off": "Spin Off",
    "alternative_version": "Alternative Version",
    "alternative_setting": "Alternative Setting",
}


@dataclass
class AnimeSeriesViewDisplayEntry:
    """Template-ready display metadata, tracked locally or denormalized."""

    media_id: str
    title: str
    image: str
    media_type: str
    start_date: date | None
    is_tracked: bool
    local_entry: object | None = None

    @property
    def details_url(self):
        """Return the MAL anime details URL without provider access."""
        return reverse(
            "media_details",
            kwargs={
                "source": Sources.MAL.value,
                "media_type": MediaTypes.ANIME.value,
                "media_id": self.media_id,
                "title": slugify(self.title),
            },
        )


@dataclass
class AnimeSeriesViewGroup:
    """Template-ready group assembled from local media entries."""

    root_media_id: str
    display_media_id: str
    display: AnimeSeriesViewDisplayEntry
    group_kind: str
    entries: list = field(default_factory=list)
    context_parent_media_id: str | None = None
    context_relation_type: str | None = None
    context_parent_title: str = ""

    @property
    def branch_subtitle(self):
        """Return a supported branch label with an optional parent title."""
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
    entries_by_media_id = {
        str(entry.item.media_id): entry for entry in entries
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
                "display": _local_display(entry),
                "group_kind": "singleton",
            }
        else:
            key = (membership.projection_version, membership.root_media_id)
            display_entry = entries_by_media_id.get(membership.display_media_id)
            values = {
                "root_media_id": membership.root_media_id,
                "display_media_id": membership.display_media_id,
                "display": _membership_display(
                    membership=membership,
                    local_entry=display_entry,
                ),
                "group_kind": membership.group_kind,
                "context_parent_media_id": membership.context_parent_media_id,
                "context_relation_type": membership.context_relation_type,
                "context_parent_title": membership.context_parent_title,
            }
        if key not in groups:
            groups[key] = AnimeSeriesViewGroup(**values)
            group_order.append(key)
        groups[key].entries.append(entry)

    resolved_groups = [groups[key] for key in group_order]
    for group in resolved_groups:
        if group.context_parent_title or not group.context_parent_media_id:
            continue
        parent_entry = entries_by_media_id.get(group.context_parent_media_id)
        if parent_entry is not None:
            group.context_parent_title = parent_entry.item.title
    return resolved_groups


def _local_display(entry):
    return AnimeSeriesViewDisplayEntry(
        media_id=str(entry.item.media_id),
        title=str(entry.item.title),
        image=str(entry.item.image),
        media_type=str(entry.item.media_type),
        start_date=None,
        is_tracked=True,
        local_entry=entry,
    )


def _membership_display(*, membership, local_entry):
    if local_entry is not None:
        return AnimeSeriesViewDisplayEntry(
            media_id=str(local_entry.item.media_id),
            title=str(local_entry.item.title),
            image=str(local_entry.item.image),
            media_type=str(membership.display_media_type),
            start_date=membership.display_start_date,
            is_tracked=True,
            local_entry=local_entry,
        )
    return AnimeSeriesViewDisplayEntry(
        media_id=str(membership.display_media_id),
        title=str(membership.display_title),
        image=str(membership.display_image),
        media_type=str(membership.display_media_type),
        start_date=membership.display_start_date,
        is_tracked=False,
    )
