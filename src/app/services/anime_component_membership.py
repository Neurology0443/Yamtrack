"""Persist stable per-user anime continuity component memberships."""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from app.models import (
    Anime,
    AnimeImportComponentMembership,
    MediaTypes,
    Sources,
)

LOCAL_CONTINUITY_RELATIONS = frozenset(
    {
        "prequel",
        "sequel",
        "full_story",
        "summary",
        "special",
        "ova",
        "tv_special",
        "side_story",
    },
)
PARENT_TO_CHILD_RELATIONS = frozenset(
    {
        "sequel",
        "summary",
        "special",
        "ova",
        "tv_special",
        "side_story",
    },
)


@dataclass(frozen=True)
class LocalComponentMembership:
    """One anime mapped to the root of its local narrative component."""

    media_id: str
    component_root_mal_id: str
    component_size: int


class AnimeImportComponentMembershipService:
    """Synchronize tracked anime memberships without affecting scan scheduling."""

    def resolve_local_memberships(
        self,
        *,
        snapshot,
        selected_media_ids: Iterable[str],
    ) -> list[LocalComponentMembership]:
        """Expand selected entries through local relations and resolve branch roots."""
        selected_ids = {
            str(media_id)
            for media_id in selected_media_ids
            if media_id not in (None, "")
        }
        if not selected_ids:
            return []

        adjacency: dict[str, set[str]] = defaultdict(set)
        child_media_ids = set()
        for relation in getattr(snapshot, "all_normalized_relations", []):
            relation_type = str(relation.relation_type or "").lower()
            if relation_type not in LOCAL_CONTINUITY_RELATIONS:
                continue
            source_id = str(relation.source_media_id)
            target_id = str(relation.target_media_id)
            adjacency[source_id].add(target_id)
            adjacency[target_id].add(source_id)
            child_media_ids.add(
                self._relation_child_id(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                ),
            )

        memberships = []
        visited = set()
        for selected_id in sorted(selected_ids, key=self._stable_media_id_key):
            if selected_id in visited:
                continue
            component = self._connected_component(
                selected_id,
                adjacency=adjacency,
            )
            visited.update(component)
            root_id = self._component_root(
                component,
                child_media_ids=child_media_ids,
            )
            memberships.extend(
                LocalComponentMembership(
                    media_id=media_id,
                    component_root_mal_id=root_id,
                    component_size=len(component),
                )
                for media_id in component
            )
        return memberships

    def _connected_component(
        self,
        media_id: str,
        *,
        adjacency: dict[str, set[str]],
    ) -> set[str]:
        component = set()
        queue = deque([media_id])
        while queue:
            current_id = queue.popleft()
            if current_id in component:
                continue
            component.add(current_id)
            queue.extend(adjacency.get(current_id, set()) - component)
        return component

    def _relation_child_id(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> str:
        if relation_type in PARENT_TO_CHILD_RELATIONS:
            return target_id
        return source_id

    def _component_root(
        self,
        media_ids: set[str],
        *,
        child_media_ids: set[str],
    ) -> str:
        root_candidates = media_ids - child_media_ids
        return min(
            root_candidates or media_ids,
            key=self._stable_media_id_key,
        )

    def _stable_media_id_key(self, media_id: str) -> tuple[int, int | str]:
        try:
            return (0, int(media_id))
        except ValueError:
            return (1, media_id)

    @transaction.atomic
    def record_tracked_memberships(
        self,
        *,
        user_id: int,
        memberships: Iterable[LocalComponentMembership],
        source_profile_key: str,
    ) -> int:
        """Upsert resolved local roots for tracked component members."""
        membership_by_media_id = {
            str(membership.media_id): membership
            for membership in memberships
        }
        if not membership_by_media_id:
            return 0

        tracked_media_ids = set(
            Anime.objects.filter(
                user_id=user_id,
                item__media_id__in=membership_by_media_id,
                item__source=Sources.MAL.value,
                item__media_type=MediaTypes.ANIME.value,
            )
            .values_list("item__media_id", flat=True)
            .distinct(),
        )
        if not tracked_media_ids:
            return 0

        stored_memberships = list(
            AnimeImportComponentMembership.objects.filter(
                user_id=user_id,
                media_id__in=tracked_media_ids,
            ),
        )
        existing_media_ids = {
            membership.media_id for membership in stored_memberships
        }
        now = timezone.now()
        for membership in stored_memberships:
            resolved = membership_by_media_id[membership.media_id]
            membership.component_root_mal_id = resolved.component_root_mal_id
            membership.component_size = resolved.component_size
            membership.source_profile_key = source_profile_key
            membership.updated_at = now
        AnimeImportComponentMembership.objects.bulk_update(
            stored_memberships,
            [
                "component_root_mal_id",
                "component_size",
                "source_profile_key",
                "updated_at",
            ],
        )
        AnimeImportComponentMembership.objects.bulk_create(
            [
                AnimeImportComponentMembership(
                    user_id=user_id,
                    media_id=media_id,
                    component_root_mal_id=(
                        membership_by_media_id[media_id].component_root_mal_id
                    ),
                    component_size=membership_by_media_id[media_id].component_size,
                    source_profile_key=source_profile_key,
                )
                for media_id in sorted(tracked_media_ids - existing_media_ids)
            ],
        )
        return len(tracked_media_ids)
