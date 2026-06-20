"""Read-only assembly of the Anime Series View from persisted memberships."""

from dataclasses import dataclass, field

from app.models import AnimeLocalSeriesMembership
from app.services.anime_local_series_projection import SERIES_VIEW_PROFILE_KEY


@dataclass
class AnimeSeriesViewGroup:
    """Template-ready logical anime group."""

    root_media_id: str
    group_kind: str
    display_media_id: str = ""
    entries: list = field(default_factory=list)
    context_parent_media_id: str = ""
    context_relation_type: str = ""

    @property
    def display_entry(self):
        """Return the persisted representative entry with safe fallbacks."""
        display_entry = next(
            (
                entry
                for entry in self.entries
                if str(entry.item.media_id) == self.display_media_id
            ),
            None,
        )
        if display_entry is not None:
            return display_entry
        root_entry = next(
            (
                entry
                for entry in self.entries
                if str(entry.item.media_id) == self.root_media_id
            ),
            None,
        )
        return root_entry or self.entries[0]

    @property
    def title(self):
        """Return the representative entry title."""
        return self.display_entry.item.title


def build_anime_series_view(*, media_entries, user_id):
    """Group filtered anime entries using DB memberships only."""
    entries = list(media_entries)
    media_ids = [str(entry.item.media_id) for entry in entries]
    memberships = AnimeLocalSeriesMembership.objects.filter(
        user_id=user_id,
        source_profile_key=SERIES_VIEW_PROFILE_KEY,
        media_id__in=media_ids,
    ).order_by("-updated_at", "-id")
    membership_by_media_id = {}
    for membership in memberships:
        membership_by_media_id.setdefault(membership.media_id, membership)

    groups = {}
    order = []
    for entry in entries:
        media_id = str(entry.item.media_id)
        membership = membership_by_media_id.get(media_id)
        if membership is None:
            key = ("singleton", media_id)
            root_media_id = media_id
            display_media_id = media_id
            group_kind = "singleton"
            context_parent_media_id = ""
            context_relation_type = ""
        else:
            key = (membership.resolver_version, membership.root_media_id)
            root_media_id = membership.root_media_id
            display_media_id = (
                membership.display_media_id or membership.root_media_id
            )
            group_kind = membership.group_kind
            context_parent_media_id = membership.context_parent_media_id
            context_relation_type = membership.context_relation_type
        if key not in groups:
            groups[key] = AnimeSeriesViewGroup(
                root_media_id=root_media_id,
                display_media_id=display_media_id,
                group_kind=group_kind,
                context_parent_media_id=context_parent_media_id,
                context_relation_type=context_relation_type,
            )
            order.append(key)
        groups[key].entries.append(entry)
    return [groups[key] for key in order]
