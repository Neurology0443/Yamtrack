"""Build read-only, user-specific anime continuity groups for the media list."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.models import AnimeImportScanState
from app.services import anime_franchise_cache

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from app.models import Anime, Item
    from users.models import User


PARENT_BY_DEFAULT_SECTION_KEYS = frozenset(
    {
        "series",
        "series_line",
        "continuity_extras",
        "main_story_extra",
        "main_story_extras",
        "movies",
        "special",
        "specials",
        "ova",
        "ovas",
        "tv_special",
        "tv_specials",
    },
)
SEPARATE_SECTION_KINDS = {
    "alternatives": "alternative_branch",
    "alternative_versions": "alternative_branch",
    "alternative_settings": "alternative_branch",
    "spin_offs": "spin_off_branch",
}
SEPARATE_BY_DEFAULT_RELATIONS = frozenset(
    {
        "alternative_version",
        "alternative_setting",
        "spin_off",
    },
)
SEPARATE_RELATION_KINDS = {
    "alternative_version": "alternative_branch",
    "alternative_setting": "alternative_branch",
    "spin_off": "spin_off_branch",
}
PARENT_BY_DEFAULT_RELATIONS = frozenset(
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
        "side_story",
        "special",
        "ova",
        "tv_special",
        "summary",
    },
)


@dataclass(frozen=True)
class BranchDecision:
    """Classifier result for one payload membership."""

    separate: bool
    group_kind: str


class AnimeSeriesBranchClassifier:
    """Centralize display-branch decisions for cached franchise entries."""

    def classify(
        self,
        *,
        section_key: str,
        relation_type: str,
        parent_known: bool = True,
    ) -> BranchDecision:
        """Return a deterministic display-group decision for one membership."""
        section_key = str(section_key or "").lower()
        relation_type = str(relation_type or "").lower()

        branch_kind = SEPARATE_SECTION_KINDS.get(
            section_key,
            SEPARATE_RELATION_KINDS.get(relation_type),
        )
        if relation_type in SEPARATE_BY_DEFAULT_RELATIONS or branch_kind:
            decision = BranchDecision(
                separate=True,
                group_kind=branch_kind,
            )
        elif (
            section_key in PARENT_BY_DEFAULT_SECTION_KEYS
            or relation_type in PARENT_BY_DEFAULT_RELATIONS
            or parent_known
        ):
            decision = BranchDecision(
                separate=False,
                group_kind="main_continuity",
            )
        else:
            decision = BranchDecision(
                separate=True,
                group_kind="singleton",
            )
        return decision


@dataclass
class AnimeSeriesEntry:
    """One tracked anime shown inside a continuity group."""

    media_id: str
    title: str
    score: Decimal | None
    progress: int
    max_progress: int | None
    start_date: datetime | None
    end_date: datetime | None

    @property
    def progress_ratio(self) -> float:
        """Return normalized progress for group-level sorting."""
        if not self.max_progress:
            return 0
        return min(self.progress / self.max_progress, 1)


@dataclass
class AnimeSeriesGroup:
    """Template-ready group representing one local anime continuity."""

    group_key: str
    display_title: str
    display_image: str
    detail_item: Item
    entries: list[AnimeSeriesEntry]
    group_kind: str
    subtitle: str = ""
    user_score: Decimal | None = None
    best_score: Decimal | None = None
    best_progress_ratio: float = 0
    earliest_start_date: datetime | None = None
    latest_end_date: datetime | None = None


@dataclass(frozen=True)
class _PayloadMembership:
    parent_key: str
    section_key: str
    relation_type: str
    payload: dict
    entry_data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BranchContext:
    """External relation that gives an Alternative or Spin-off UX context."""

    kind: str
    parent_title: str


@dataclass(frozen=True)
class _ResolvedEntry:
    media: Anime
    group_key: str
    group_kind: str
    membership: _PayloadMembership | None
    lookup: anime_franchise_cache.FranchisePayloadLookup
    branch_context: BranchContext | None = None


class AnimeSeriesListService:
    """Group a filtered anime queryset without fetching or mutating metadata."""

    def __init__(self, classifier: AnimeSeriesBranchClassifier | None = None):
        """Initialize with an optional classifier override for tests."""
        self.classifier = classifier or AnimeSeriesBranchClassifier()

    def build_groups(
        self,
        *,
        target_user: User,
        anime_queryset: QuerySet,
        sort_filter: str,
    ) -> list[AnimeSeriesGroup]:
        """Return sorted continuity groups for the already-filtered anime."""
        anime_list = list(anime_queryset)
        if not anime_list:
            return []

        media_ids = [str(anime.item.media_id) for anime in anime_list]
        lookups = {
            media_id: anime_franchise_cache.load_payload_for_media(
                media_id,
                touch=False,
            )
            for media_id in media_ids
        }
        state_roots = self._load_state_roots(target_user.id, media_ids)
        memberships = self._build_membership_index(lookups.values())
        resolved = [
            self._resolve_entry(
                anime=anime,
                lookup=lookups[str(anime.item.media_id)],
                memberships=memberships.get(str(anime.item.media_id), []),
                state_root=state_roots.get(str(anime.item.media_id), ""),
                tracked_media_ids=set(media_ids),
            )
            for anime in anime_list
        ]
        resolved = self._collapse_group_keys(resolved)

        grouped: dict[str, list[_ResolvedEntry]] = defaultdict(list)
        for entry in resolved:
            grouped[entry.group_key].append(entry)

        groups = [
            self._build_group(group_key, entries)
            for group_key, entries in grouped.items()
        ]
        return self._sort_groups(groups, sort_filter)

    def _load_state_roots(
        self,
        user_id: int,
        media_ids: list[str],
    ) -> dict[str, str]:
        states = (
            AnimeImportScanState.objects.filter(
                user_id=user_id,
                seed_mal_id__in=media_ids,
            )
            .exclude(component_root_mal_id="")
            .order_by("seed_mal_id", "-last_success_at", "profile_key")
        )
        roots: dict[str, str] = {}
        for state in states:
            roots.setdefault(
                str(state.seed_mal_id),
                str(state.component_root_mal_id),
            )
        return roots

    def _build_membership_index(
        self,
        lookups,
    ) -> dict[str, list[_PayloadMembership]]:
        index: dict[str, list[_PayloadMembership]] = defaultdict(list)
        seen_payloads: set[tuple[str, int]] = set()

        for lookup in lookups:
            payload = lookup.payload
            if not isinstance(payload, dict):
                continue
            parent_key = str(
                payload.get("canonical_root_media_id")
                or payload.get("root_media_id")
                or lookup.canonical_media_id
            )
            payload_identity = (parent_key, id(payload))
            if payload_identity in seen_payloads:
                continue
            seen_payloads.add(payload_identity)
            series = payload.get("series", {})
            series_key = str(series.get("key") or "series")
            for entry in series.get("entries", []):
                self._add_membership(
                    index,
                    entry,
                    parent_key=parent_key,
                    section_key=series_key,
                    payload=payload,
                )
            for section in payload.get("sections", []):
                section_key = str(section.get("key") or "")
                for entry in section.get("entries", []):
                    self._add_membership(
                        index,
                        entry,
                        parent_key=parent_key,
                        section_key=section_key,
                        payload=payload,
                    )
        return index

    def _add_membership(
        self,
        index,
        entry,
        *,
        parent_key,
        section_key,
        payload,
    ) -> None:
        if not isinstance(entry, dict) or entry.get("media_id") in (None, ""):
            return
        media_id = str(entry["media_id"])
        index[media_id].append(
            _PayloadMembership(
                parent_key=parent_key,
                section_key=section_key,
                relation_type=str(entry.get("relation_type") or ""),
                payload=payload,
                entry_data=entry,
            ),
        )

    def _resolve_entry(
        self,
        *,
        anime,
        lookup,
        memberships,
        state_root,
        tracked_media_ids,
    ) -> _ResolvedEntry:
        media_id = str(anime.item.media_id)
        branch_context = self._branch_context(
            memberships,
            current_media_id=media_id,
            tracked_media_ids=tracked_media_ids,
        )
        if branch_context is not None:
            return _ResolvedEntry(
                media=anime,
                group_key=media_id,
                group_kind=branch_context.kind,
                membership=None,
                lookup=lookup,
                branch_context=branch_context,
            )

        affiliation = self._affiliation_membership(
            memberships,
            state_root=state_root,
            current_media_id=media_id,
            tracked_media_ids=tracked_media_ids,
        )
        if affiliation is not None:
            decision = self.classifier.classify(
                section_key=affiliation.section_key,
                relation_type=affiliation.relation_type,
            )
            return _ResolvedEntry(
                media=anime,
                group_key=affiliation.parent_key,
                group_kind=decision.group_kind,
                membership=affiliation,
                lookup=lookup,
            )

        if self._is_direct_local_payload(lookup, media_id):
            return _ResolvedEntry(
                media=anime,
                group_key=media_id,
                group_kind="main_continuity",
                membership=None,
                lookup=lookup,
            )
        if state_root:
            return _ResolvedEntry(
                media=anime,
                group_key=state_root,
                group_kind="main_continuity",
                membership=None,
                lookup=lookup,
            )
        return _ResolvedEntry(
            media=anime,
            group_key=media_id,
            group_kind="singleton",
            membership=None,
            lookup=lookup,
        )

    def _branch_context(
        self,
        memberships: list[_PayloadMembership],
        *,
        current_media_id: str,
        tracked_media_ids: set[str],
    ) -> BranchContext | None:
        candidates = []
        for membership in memberships:
            if membership.parent_key == current_media_id:
                continue
            branch_kind = SEPARATE_SECTION_KINDS.get(
                membership.section_key.lower(),
                SEPARATE_RELATION_KINDS.get(membership.relation_type.lower()),
            )
            if branch_kind is None or self._local_payload_links_to(
                memberships,
                current_media_id=current_media_id,
                target_media_id=membership.parent_key,
                relation_types=SEPARATE_BY_DEFAULT_RELATIONS,
                section_keys=frozenset(SEPARATE_SECTION_KINDS),
            ):
                continue
            candidates.append((membership, branch_kind))

        if not candidates:
            return None

        membership, branch_kind = min(
            candidates,
            key=lambda candidate: (
                0 if candidate[0].parent_key in tracked_media_ids else 1,
                candidate[0].parent_key,
            ),
        )
        return BranchContext(
            kind=branch_kind,
            parent_title=self._payload_parent_title(membership),
        )

    def _local_payload_links_to(
        self,
        memberships: list[_PayloadMembership],
        *,
        current_media_id: str,
        target_media_id: str,
        relation_types: frozenset[str],
        section_keys: frozenset[str] = frozenset(),
    ) -> bool:
        for membership in memberships:
            if membership.parent_key != current_media_id:
                continue
            for block in [
                membership.payload.get("series", {}),
                *membership.payload.get("sections", []),
            ]:
                for entry in block.get("entries", []):
                    if str(entry.get("media_id") or "") != target_media_id:
                        continue
                    relation_type = str(entry.get("relation_type") or "").lower()
                    section_key = str(block.get("key") or "").lower()
                    if relation_type in relation_types or section_key in section_keys:
                        return True
        return False

    def _affiliation_membership(
        self,
        memberships: list[_PayloadMembership],
        *,
        state_root: str,
        current_media_id: str,
        tracked_media_ids: set[str],
    ) -> _PayloadMembership | None:
        candidates = []
        for membership in memberships:
            if (
                membership.parent_key != current_media_id
                and self._local_payload_links_to(
                    memberships,
                    current_media_id=current_media_id,
                    target_media_id=membership.parent_key,
                    relation_types=PARENT_TO_CHILD_RELATIONS,
                )
            ):
                continue
            decision = self.classifier.classify(
                section_key=membership.section_key,
                relation_type=membership.relation_type,
            )
            if decision.separate:
                continue
            candidates.append(membership)
        if not candidates:
            return None

        def priority(membership):
            section_key = membership.section_key.lower()
            external_parent = membership.parent_key != current_media_id
            parent_section = section_key in PARENT_BY_DEFAULT_SECTION_KEYS
            return (
                0 if external_parent else 1,
                0 if state_root and membership.parent_key == state_root else 1,
                0 if membership.parent_key in tracked_media_ids else 1,
                0 if parent_section else 1,
                membership.parent_key,
            )

        return min(candidates, key=priority)

    def _collapse_group_keys(
        self,
        resolved_entries: list[_ResolvedEntry],
    ) -> list[_ResolvedEntry]:
        by_media_id = {
            str(entry.media.item.media_id): entry for entry in resolved_entries
        }
        collapsed = []
        for entry in resolved_entries:
            group_key = entry.group_key
            seen = {str(entry.media.item.media_id)}
            while group_key in by_media_id and group_key not in seen:
                seen.add(group_key)
                next_key = by_media_id[group_key].group_key
                if next_key == group_key:
                    break
                group_key = next_key
            collapsed.append(replace(entry, group_key=group_key))
        return collapsed

    def _is_direct_local_payload(self, lookup, media_id: str) -> bool:
        payload = lookup.payload
        return (
            isinstance(payload, dict)
            and not lookup.alias_hit
            and str(
                payload.get("canonical_root_media_id")
                or payload.get("root_media_id")
                or ""
            )
            == media_id
        )

    def _payload_parent_title(self, membership: _PayloadMembership) -> str:
        payload = membership.payload
        display_title = str(payload.get("display_title") or "").strip()
        if display_title:
            return display_title
        for entry in payload.get("series", {}).get("entries", []):
            if str(entry.get("media_id") or "") == membership.parent_key:
                return str(entry.get("title") or "").strip()
        return ""

    def _build_group(
        self,
        group_key: str,
        resolved_entries: list[_ResolvedEntry],
    ) -> AnimeSeriesGroup:
        representative = self._choose_representative(group_key, resolved_entries)
        entries = [
            AnimeSeriesEntry(
                media_id=str(resolved.media.item.media_id),
                title=resolved.media.item.title,
                score=resolved.media.score,
                progress=resolved.media.progress,
                max_progress=getattr(resolved.media, "max_progress", None),
                start_date=resolved.media.start_date,
                end_date=resolved.media.end_date,
            )
            for resolved in resolved_entries
        ]
        entries.sort(
            key=lambda entry: (
                entry.start_date is None,
                entry.start_date or datetime.max.replace(tzinfo=UTC),
                entry.title.casefold(),
                entry.media_id,
            ),
        )

        payload = self._group_payload(group_key, resolved_entries)
        branch_context = next(
            (
                entry.branch_context
                for entry in resolved_entries
                if entry.branch_context is not None
            ),
            None,
        )
        scores = [entry.score for entry in entries if entry.score is not None]
        starts = [entry.start_date for entry in entries if entry.start_date is not None]
        ends = [entry.end_date for entry in entries if entry.end_date is not None]
        representative_media = representative.media
        display_title = (
            payload.get("display_title")
            if payload and str(payload.get("display_title") or "").strip()
            else representative_media.item.title
        )
        group_kind = (
            branch_context.kind
            if branch_context is not None
            else representative.group_kind
        )

        return AnimeSeriesGroup(
            group_key=group_key,
            display_title=str(display_title),
            display_image=representative_media.item.image,
            detail_item=representative_media.item,
            entries=entries,
            group_kind=group_kind,
            subtitle=self._subtitle(branch_context),
            user_score=representative_media.score,
            best_score=max(scores) if scores else None,
            best_progress_ratio=max(
                (entry.progress_ratio for entry in entries),
                default=0,
            ),
            earliest_start_date=min(starts) if starts else None,
            latest_end_date=max(ends) if ends else None,
        )

    def _subtitle(self, context: BranchContext | None) -> str:
        if context is None:
            return ""
        prefix = (
            "Alternative continuity"
            if context.kind == "alternative_branch"
            else "Spin-off continuity"
        )
        return f"{prefix} · {context.parent_title}" if context.parent_title else prefix

    def _choose_representative(
        self,
        group_key: str,
        entries: list[_ResolvedEntry],
    ) -> _ResolvedEntry:
        def priority(entry):
            media_id = str(entry.media.item.media_id)
            membership = entry.membership
            anime_media_type = (
                str(membership.entry_data.get("anime_media_type") or "")
                if membership
                else ""
            )
            in_series = bool(
                membership
                and membership.section_key.lower() in {"series", "series_line"}
            )
            return (
                0 if media_id == group_key else 1,
                0 if in_series else 1,
                0 if anime_media_type == "tv" else 1,
                entry.media.start_date is None,
                entry.media.start_date or datetime.max.replace(tzinfo=UTC),
                entry.media.item.title.casefold(),
                media_id,
            )

        return min(entries, key=priority)

    def _group_payload(
        self,
        group_key: str,
        entries: list[_ResolvedEntry],
    ) -> dict | None:
        candidates = []
        for entry in entries:
            if entry.lookup.payload:
                candidates.append(entry.lookup.payload)
            if entry.membership:
                candidates.append(entry.membership.payload)
        for payload in candidates:
            payload_root = str(
                payload.get("canonical_root_media_id")
                or payload.get("root_media_id")
                or ""
            )
            if payload_root == group_key:
                return payload
        return None

    def _sort_groups(
        self,
        groups: list[AnimeSeriesGroup],
        sort_filter: str,
    ) -> list[AnimeSeriesGroup]:
        def fallback(group):
            return group.display_title.casefold(), group.group_key

        if sort_filter == "score":
            return sorted(
                groups,
                key=lambda group: (
                    group.best_score is None,
                    -(group.best_score or Decimal(0)),
                    *fallback(group),
                ),
            )
        if sort_filter == "progress":
            return sorted(
                groups,
                key=lambda group: (-group.best_progress_ratio, *fallback(group)),
            )
        if sort_filter == "start_date":
            return sorted(
                groups,
                key=lambda group: (
                    group.earliest_start_date is None,
                    group.earliest_start_date
                    or datetime.max.replace(tzinfo=UTC),
                    *fallback(group),
                ),
            )
        if sort_filter == "end_date":
            return sorted(
                groups,
                key=lambda group: (
                    group.latest_end_date is None,
                    -(
                        group.latest_end_date.timestamp()
                        if group.latest_end_date
                        else 0
                    ),
                    *fallback(group),
                ),
            )
        return sorted(groups, key=fallback)
