"""Read-only assembly of template-ready Anime Series View cards."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AnimeSeriesViewMembership, MediaTypes, Sources


@dataclass
class AnimeSeriesViewDisplayEntry:
    """One tracked anime displayed inside a franchise card."""

    media_id: str
    title: str
    image: str
    media_type: str
    local_entry: object | None = None


@dataclass
class AnimeSeriesViewGroup:
    """One persisted franchise or explicit singleton card."""

    root_media_id: str
    display_media_id: str
    display_title: str
    display_image: str
    display_media_type: str
    display_start_date: object | None
    group_kind: str
    entries: list[AnimeSeriesViewDisplayEntry] = field(default_factory=list)

    @property
    def display_item(self):
        """Return a metadata-like root object accepted by the URL template filter."""
        return {
            "media_id": self.display_media_id,
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": self.display_title,
            "image": self.display_image,
        }


@dataclass
class AnimeSeriesViewResult:
    """Series View groups plus entries still awaiting projection."""

    groups: list[AnimeSeriesViewGroup]
    unprojected_count: int = 0


def build_anime_series_view(*, media_entries, user_id):
    """Group existing entries only from persisted memberships, preserving order."""
    media_entries = list(media_entries)
    media_ids = [entry.item.media_id for entry in media_entries]
    memberships = {
        membership.media_id: membership
        for membership in AnimeSeriesViewMembership.objects.filter(
            user_id=user_id,
            media_id__in=media_ids,
        )
    }

    groups_by_root = {}
    groups = []
    unprojected_count = 0
    for local_entry in media_entries:
        membership = memberships.get(local_entry.item.media_id)
        if membership is None:
            unprojected_count += 1
            continue

        group = groups_by_root.get(membership.root_media_id)
        if group is None:
            group = AnimeSeriesViewGroup(
                root_media_id=membership.root_media_id,
                display_media_id=membership.display_media_id,
                display_title=membership.display_title,
                display_image=membership.display_image,
                display_media_type=membership.display_media_type,
                display_start_date=membership.display_start_date,
                group_kind=membership.group_kind,
            )
            groups_by_root[membership.root_media_id] = group
            groups.append(group)

        group.entries.append(
            AnimeSeriesViewDisplayEntry(
                media_id=local_entry.item.media_id,
                title=local_entry.item.title,
                image=local_entry.item.image,
                media_type=local_entry.item.media_type,
                local_entry=local_entry,
            )
        )

    return AnimeSeriesViewResult(
        groups=groups,
        unprojected_count=unprojected_count,
    )
