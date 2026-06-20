"""Read-only assembly of the Anime Series View from persisted memberships."""

from dataclasses import dataclass, field

from app.models import AnimeLocalSeriesMembership
from app.services.anime_local_series_projection import SERIES_VIEW_PROFILE_KEY

BRANCH_LABELS = {
    "spin_off": "Spin Off",
    "alternative_version": "Alternative Version",
    "alternative_setting": "Alternative Setting",
}


@dataclass
class AnimeSeriesViewGroup:
    """Template-ready logical anime group."""

    root_media_id: str
    group_kind: str
    display_media_id: str = ""
    entries: list = field(default_factory=list)
    context_parent_media_id: str = ""
    context_relation_type: str = ""
    context_parent_title: str = ""

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
        return self.display_title

    @property
    def display_title(self):
        """Return the representative entry title for templates."""
        return self.display_entry.item.title

    @property
    def branch_label(self):
        """Return a readable label for supported branch relations."""
        return BRANCH_LABELS.get(self.context_relation_type, "")

    @property
    def branch_parent_title(self):
        """Return a locally available parent title without external lookup."""
        parent_entry = next(
            (
                entry
                for entry in self.entries
                if str(entry.item.media_id) == self.context_parent_media_id
            ),
            None,
        )
        if parent_entry is not None:
            return parent_entry.item.title
        return self.context_parent_title

    @property
    def branch_subtitle(self):
        """Return a template-ready branch label and optional parent title."""
        if not self.branch_label:
            return ""
        if self.branch_parent_title:
            return f"{self.branch_label} • {self.branch_parent_title}"
        return self.branch_label


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
    titles_by_media_id = {
        str(entry.item.media_id): entry.item.title for entry in entries
    }
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
    resolved_groups = [groups[key] for key in order]
    for group in resolved_groups:
        group.context_parent_title = titles_by_media_id.get(
            group.context_parent_media_id,
            "",
        )
    return resolved_groups
