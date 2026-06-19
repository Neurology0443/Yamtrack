"""Read-only projection of tracked anime into persisted local series groups."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AnimeLocalSeriesMembership, Item, MediaTypes, Sources
from app.services.anime_local_series_constants import (
    LOCAL_SERIES_VIEW_PROFILE_KEY,
)


@dataclass
class AnimeSeriesListGroup:
    """Template-ready group of tracked anime entries."""

    root_media_id: str
    group_kind: str
    member_media_ids: list[str] = field(default_factory=list)
    entries: list = field(default_factory=list)
    root_title: str = ""
    context_parent_media_id: str = ""
    context_parent_title: str = ""
    context_relation_type: str = ""
    context_label: str = ""

    @property
    def title(self) -> str:
        """Return the displayed group title."""
        root_entry = next(
            (
                entry
                for entry in self.entries
                if str(entry.item.media_id) == self.root_media_id
            ),
            None,
        )
        if root_entry is not None:
            return root_entry.item.title
        if self.root_title:
            return self.root_title
        return self.entries[0].item.title

    @property
    def representative_entry(self):
        """Return the single media entry rendered for this group."""
        return next(
            (
                entry
                for entry in self.entries
                if str(entry.item.media_id) == self.root_media_id
            ),
            self.entries[0],
        )


def project_anime_series_groups(
    *,
    media_queryset,
    user_id,
) -> list[AnimeSeriesListGroup]:
    """Build ordered logical groups without loading full media objects."""
    media_ids_in_order = [
        str(media_id)
        for media_id in media_queryset.values_list(
            "item__media_id",
            flat=True,
        )
    ]
    if not media_ids_in_order:
        return []

    memberships_by_media_id = {}
    memberships = AnimeLocalSeriesMembership.objects.filter(
        user_id=user_id,
        source_profile_key=LOCAL_SERIES_VIEW_PROFILE_KEY,
        media_id__in=media_ids_in_order,
    ).order_by("-updated_at", "-id")
    for membership in memberships:
        memberships_by_media_id.setdefault(membership.media_id, membership)

    groups_by_key = {}
    for media_id in media_ids_in_order:
        membership = memberships_by_media_id.get(media_id)
        if membership is None:
            group_key = ("singleton", media_id)
            group = AnimeSeriesListGroup(
                root_media_id=media_id,
                group_kind="singleton",
            )
        else:
            group_key = (membership.resolver_version, membership.root_media_id)
            group = AnimeSeriesListGroup(
                root_media_id=membership.root_media_id,
                group_kind=membership.group_kind,
                context_parent_media_id=(
                    membership.context_parent_media_id or ""
                ),
                context_relation_type=membership.context_relation_type or "",
            )

        resolved_group = groups_by_key.setdefault(group_key, group)
        resolved_group.member_media_ids.append(media_id)

    groups = list(groups_by_key.values())
    context_parent_ids = {
        group.context_parent_media_id
        for group in groups
        if group.context_parent_media_id
    }
    title_media_ids = context_parent_ids | {
        group.root_media_id for group in groups
    }
    titles_by_media_id = dict(
        Item.objects.filter(
            media_id__in=title_media_ids,
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
        ).values_list("media_id", "title")
    )
    for group in groups:
        group.root_title = titles_by_media_id.get(group.root_media_id, "")
        group.context_parent_title = titles_by_media_id.get(
            group.context_parent_media_id,
            "",
        )
        group.context_label = _context_label(
            group.context_relation_type,
            group.context_parent_title,
            group.context_parent_media_id,
        )
    return groups


def hydrate_anime_series_groups(
    *,
    groups,
    media_queryset,
) -> list[AnimeSeriesListGroup]:
    """Load current-page media objects and omit groups that became empty."""
    page_media_ids = [
        media_id
        for group in groups
        for media_id in group.member_media_ids
    ]
    entries_by_media_id = {
        str(entry.item.media_id): entry
        for entry in media_queryset.filter(
            item__media_id__in=page_media_ids,
        )
    }
    for group in groups:
        group.entries = [
            entries_by_media_id[media_id]
            for media_id in group.member_media_ids
            if media_id in entries_by_media_id
        ]
    return [group for group in groups if group.entries]


def _context_label(
    relation_type: str,
    parent_title: str,
    parent_media_id: str,
) -> str:
    if not relation_type or not (parent_title or parent_media_id):
        return ""

    parent = parent_title or f"MAL {parent_media_id}"
    templates = {
        "spin_off": "Spin-off de {parent}",
        "alternative_version": "Version alternative de {parent}",
        "alternative_setting": "Univers alternatif de {parent}",
    }
    template = templates.get(relation_type)
    if template is None:
        return ""
    return template.format(parent=parent)
