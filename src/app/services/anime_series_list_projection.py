"""Read-only projection of tracked anime into persisted local series groups."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AnimeLocalSeriesMembership, Item, MediaTypes, Sources


@dataclass
class AnimeSeriesListGroup:
    """Template-ready group of tracked anime entries."""

    root_media_id: str
    group_kind: str
    entries: list = field(default_factory=list)
    context_parent_media_id: str = ""
    context_parent_title: str = ""
    context_relation_type: str = ""
    context_relation_label: str = ""

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
        return (root_entry or self.entries[0]).item.title


def project_anime_series_groups(
    *,
    media_entries,
    user_id,
) -> list[AnimeSeriesListGroup]:
    """Group filtered anime entries from persisted memberships only."""
    entries = list(media_entries)
    if not entries:
        return []

    media_ids = [str(entry.item.media_id) for entry in entries]
    memberships_by_media_id = {}
    memberships = AnimeLocalSeriesMembership.objects.filter(
        user_id=user_id,
        media_id__in=media_ids,
    ).order_by("-updated_at", "-id")
    for membership in memberships:
        memberships_by_media_id.setdefault(membership.media_id, membership)

    groups_by_key = {}
    for entry in entries:
        media_id = str(entry.item.media_id)
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
                context_relation_label=_relation_label(
                    membership.context_relation_type
                ),
            )

        resolved_group = groups_by_key.setdefault(group_key, group)
        resolved_group.entries.append(entry)

    groups = list(groups_by_key.values())
    media_order = {
        media_id: index for index, media_id in enumerate(media_ids)
    }
    for group in groups:
        group.entries.sort(
            key=lambda entry: (
                str(entry.item.media_id) != group.root_media_id,
                media_order[str(entry.item.media_id)],
            )
        )

    context_parent_ids = {
        group.context_parent_media_id
        for group in groups
        if group.context_parent_media_id
    }
    context_titles = dict(
        Item.objects.filter(
            media_id__in=context_parent_ids,
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
        ).values_list("media_id", "title")
    )
    for group in groups:
        group.context_parent_title = context_titles.get(
            group.context_parent_media_id,
            "",
        )
    return groups


def _relation_label(relation_type: str | None) -> str:
    if not relation_type:
        return ""
    return str(relation_type).replace("_", " ").title()
