"""Build read-only, user-specific anime continuity groups for the media list."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
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
CONDITIONAL_BRANCH_RELATIONS = frozenset({"side_story"})
PARENT_BY_DEFAULT_RELATIONS = frozenset(
    {
        "prequel",
        "sequel",
        "full_story",
        "summary",
        "special",
        "ova",
        "tv_special",
    },
)
MIN_FOLLOWED_BRANCH_ENTRIES = 2


@dataclass(frozen=True)
class BranchDecision:
    """Classifier result for one payload membership."""

    separate: bool
    group_role: str
    group_kind: str


class AnimeSeriesBranchClassifier:
    """Centralize display-branch decisions for cached franchise entries."""

    def classify(
        self,
        *,
        section_key: str,
        relation_type: str,
        has_followed_local_prequel_or_sequel: bool = False,
        followed_local_branch_size: int = 1,
        has_meaningful_local_branch_payload: bool = False,
        is_tv_with_followed_prequel_or_sequel: bool = False,
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
            role = (
                "alternative_version"
                if branch_kind == "alternative_branch"
                else "spin_off"
            )
            decision = BranchDecision(
                separate=True,
                group_role=role,
                group_kind=branch_kind,
            )
        elif relation_type in CONDITIONAL_BRANCH_RELATIONS:
            separate = (
                has_followed_local_prequel_or_sequel
                or followed_local_branch_size >= MIN_FOLLOWED_BRANCH_ENTRIES
                or has_meaningful_local_branch_payload
                or is_tv_with_followed_prequel_or_sequel
            )
            decision = BranchDecision(
                separate=separate,
                group_role="side_story",
                group_kind=(
                    "side_story_branch" if separate else "main_continuity"
                ),
            )
        elif section_key in {"series", "series_line"}:
            decision = BranchDecision(
                separate=False,
                group_role="series",
                group_kind="main_continuity",
            )
        elif section_key in {
            "continuity_extras",
            "main_story_extra",
            "main_story_extras",
        }:
            decision = BranchDecision(
                separate=False,
                group_role="continuity_extra",
                group_kind="main_continuity",
            )
        elif (
            section_key in PARENT_BY_DEFAULT_SECTION_KEYS
            or relation_type in PARENT_BY_DEFAULT_RELATIONS
        ):
            decision = BranchDecision(
                separate=False,
                group_role="special",
                group_kind="main_continuity",
            )
        elif parent_known:
            decision = BranchDecision(
                separate=False,
                group_role="unknown",
                group_kind="main_continuity",
            )
        else:
            decision = BranchDecision(
                separate=True,
                group_role="singleton",
                group_kind="singleton",
            )
        return decision


@dataclass
class AnimeSeriesEntry:
    """One tracked anime shown inside a continuity group."""

    media: Anime
    media_id: str
    title: str
    image: str
    status: str
    score: Decimal | None
    progress: int
    max_progress: int | None
    start_date: datetime | None
    end_date: datetime | None
    section_key: str = ""
    relation_type: str = ""
    group_role: str = ""

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
    representative_media: Anime
    detail_item: Item
    entries: list[AnimeSeriesEntry]
    tracked_count: int
    statuses: dict[str, int]
    sections: list[dict]
    has_payload: bool
    alias_hit: bool
    truncated: bool
    group_kind: str
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
    alias_hit: bool
    truncated: bool
    entry_data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _ResolvedEntry:
    media: Anime
    group_key: str
    group_role: str
    group_kind: str
    membership: _PayloadMembership | None
    lookup: anime_franchise_cache.FranchisePayloadLookup


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

        grouped: dict[str, list[_ResolvedEntry]] = defaultdict(list)
        for entry in resolved:
            grouped[entry.group_key].append(entry)

        tracked_ids = set(media_ids)
        groups = [
            self._build_group(group_key, entries, tracked_ids)
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
            truncated = bool(
                payload.get("truncated") or lookup.meta.get("truncated")
            )

            series = payload.get("series", {})
            series_key = str(series.get("key") or "series")
            for entry in series.get("entries", []):
                self._add_membership(
                    index,
                    entry,
                    parent_key=parent_key,
                    section_key=series_key,
                    payload=payload,
                    alias_hit=lookup.alias_hit,
                    truncated=truncated,
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
                        alias_hit=lookup.alias_hit,
                        truncated=truncated,
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
        alias_hit,
        truncated,
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
                alias_hit=alias_hit,
                truncated=truncated,
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
        direct_local_payload = (
            lookup.payload is not None
            and not lookup.alias_hit
            and str(
                lookup.payload.get("canonical_root_media_id")
                or lookup.payload.get("root_media_id")
                or ""
            )
            == media_id
        )
        preferred_membership = self._preferred_membership(
            memberships,
            state_root=state_root,
            current_media_id=media_id,
        )

        if preferred_membership is not None:
            has_followed_local_relation = self._has_followed_local_relation(
                media_id=media_id,
                parent_media_id=preferred_membership.parent_key,
                lookup=lookup,
                tracked_media_ids=tracked_media_ids,
            )
            followed_local_branch_size = self._followed_local_branch_size(
                media_id=media_id,
                parent_media_id=preferred_membership.parent_key,
                lookup=lookup,
                tracked_media_ids=tracked_media_ids,
            )
            has_meaningful_local_payload = (
                followed_local_branch_size >= MIN_FOLLOWED_BRANCH_ENTRIES
            )
            anime_media_type = str(
                preferred_membership.entry_data.get("anime_media_type") or ""
            ).lower()
            decision = self.classifier.classify(
                section_key=preferred_membership.section_key,
                relation_type=preferred_membership.relation_type,
                has_followed_local_prequel_or_sequel=has_followed_local_relation,
                followed_local_branch_size=followed_local_branch_size,
                has_meaningful_local_branch_payload=has_meaningful_local_payload,
                is_tv_with_followed_prequel_or_sequel=(
                    anime_media_type == "tv" and has_followed_local_relation
                ),
            )
            if not decision.separate:
                return _ResolvedEntry(
                    media=anime,
                    group_key=preferred_membership.parent_key,
                    group_role=decision.group_role,
                    group_kind=decision.group_kind,
                    membership=preferred_membership,
                    lookup=lookup,
                )
            group_key = state_root or media_id
            return _ResolvedEntry(
                media=anime,
                group_key=group_key,
                group_role=decision.group_role,
                group_kind=decision.group_kind,
                membership=preferred_membership,
                lookup=lookup,
            )

        if direct_local_payload:
            return _ResolvedEntry(
                media=anime,
                group_key=media_id,
                group_role="series",
                group_kind="main_continuity",
                membership=None,
                lookup=lookup,
            )
        if state_root:
            return _ResolvedEntry(
                media=anime,
                group_key=state_root,
                group_role="series",
                group_kind="main_continuity",
                membership=None,
                lookup=lookup,
            )
        return _ResolvedEntry(
            media=anime,
            group_key=media_id,
            group_role="singleton",
            group_kind="singleton",
            membership=None,
            lookup=lookup,
        )

    def _has_followed_local_relation(
        self,
        *,
        media_id: str,
        parent_media_id: str,
        lookup: anime_franchise_cache.FranchisePayloadLookup,
        tracked_media_ids: set[str],
    ) -> bool:
        payload = lookup.payload
        if not isinstance(payload, dict):
            return False
        payload_root = str(
            payload.get("canonical_root_media_id")
            or payload.get("root_media_id")
            or ""
        )
        if payload_root != media_id:
            return False

        blocks = [payload.get("series", {}), *payload.get("sections", [])]
        for block in blocks:
            for entry in block.get("entries", []):
                entry_media_id = str(entry.get("media_id") or "")
                relation_type = str(entry.get("relation_type") or "").lower()
                if (
                    entry_media_id in tracked_media_ids
                    and entry_media_id not in (media_id, parent_media_id)
                    and relation_type in {"prequel", "sequel"}
                ):
                    return True
        return False

    def _followed_local_branch_size(
        self,
        *,
        media_id: str,
        parent_media_id: str,
        lookup: anime_franchise_cache.FranchisePayloadLookup,
        tracked_media_ids: set[str],
    ) -> int:
        """Count followed entries proven to belong to the local payload branch."""
        payload = lookup.payload
        if not isinstance(payload, dict) or lookup.alias_hit:
            return 1

        payload_root = str(
            payload.get("canonical_root_media_id")
            or payload.get("root_media_id")
            or ""
        )
        if payload_root != media_id:
            return 1

        followed_branch_ids = {media_id}
        series = payload.get("series", {})
        for entry in series.get("entries", []):
            entry_media_id = str(entry.get("media_id") or "")
            if (
                entry_media_id in tracked_media_ids
                and entry_media_id != parent_media_id
            ):
                followed_branch_ids.add(entry_media_id)

        for section in payload.get("sections", []):
            for entry in section.get("entries", []):
                entry_media_id = str(entry.get("media_id") or "")
                relation_type = str(entry.get("relation_type") or "").lower()
                if (
                    entry_media_id not in tracked_media_ids
                    or entry_media_id == parent_media_id
                ):
                    continue
                if (
                    relation_type in {"prequel", "sequel"}
                    or relation_type not in SEPARATE_BY_DEFAULT_RELATIONS
                ):
                    followed_branch_ids.add(entry_media_id)

        return len(followed_branch_ids)

    def _preferred_membership(
        self,
        memberships: list[_PayloadMembership],
        *,
        state_root: str,
        current_media_id: str,
    ) -> _PayloadMembership | None:
        if not memberships:
            return None

        def priority(membership):
            section_key = membership.section_key.lower()
            relation_type = membership.relation_type.lower()
            current_media_root = membership.parent_key == current_media_id
            state_component_root = bool(
                state_root and membership.parent_key == state_root
            )
            parent_section = section_key in PARENT_BY_DEFAULT_SECTION_KEYS
            separate_section = (
                section_key in SEPARATE_SECTION_KINDS
                or relation_type in SEPARATE_RELATION_KINDS
            )
            return (
                0 if current_media_root else 1,
                0 if state_component_root else 1,
                0 if separate_section else 1,
                0 if parent_section else 1,
                membership.parent_key,
            )

        return min(memberships, key=priority)

    def _build_group(
        self,
        group_key: str,
        resolved_entries: list[_ResolvedEntry],
        tracked_ids: set[str],
    ) -> AnimeSeriesGroup:
        representative = self._choose_representative(group_key, resolved_entries)
        entries = [
            AnimeSeriesEntry(
                media=resolved.media,
                media_id=str(resolved.media.item.media_id),
                title=resolved.media.item.title,
                image=resolved.media.item.image,
                status=resolved.media.status,
                score=resolved.media.score,
                progress=resolved.media.progress,
                max_progress=getattr(resolved.media, "max_progress", None),
                start_date=resolved.media.start_date,
                end_date=resolved.media.end_date,
                section_key=(
                    resolved.membership.section_key if resolved.membership else ""
                ),
                relation_type=(
                    resolved.membership.relation_type if resolved.membership else ""
                ),
                group_role=resolved.group_role,
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
        scores = [entry.score for entry in entries if entry.score is not None]
        starts = [entry.start_date for entry in entries if entry.start_date is not None]
        ends = [entry.end_date for entry in entries if entry.end_date is not None]
        representative_media = representative.media
        display_title = (
            payload.get("display_title")
            if payload and str(payload.get("display_title") or "").strip()
            else representative_media.item.title
        )
        kinds = Counter(entry.group_kind for entry in resolved_entries)
        group_kind = kinds.most_common(1)[0][0]

        return AnimeSeriesGroup(
            group_key=group_key,
            display_title=str(display_title),
            display_image=representative_media.item.image,
            representative_media=representative_media,
            detail_item=representative_media.item,
            entries=entries,
            tracked_count=len(entries),
            statuses=dict(Counter(entry.status for entry in entries)),
            sections=self._summarize_sections(payload, tracked_ids, entries),
            has_payload=payload is not None,
            alias_hit=any(entry.lookup.alias_hit for entry in resolved_entries),
            truncated=any(
                bool(entry.lookup.meta.get("truncated"))
                or bool(entry.lookup.payload and entry.lookup.payload.get("truncated"))
                for entry in resolved_entries
            ),
            group_kind=group_kind,
            best_score=max(scores) if scores else None,
            best_progress_ratio=max(
                (entry.progress_ratio for entry in entries),
                default=0,
            ),
            earliest_start_date=min(starts) if starts else None,
            latest_end_date=max(ends) if ends else None,
        )

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

    def _summarize_sections(
        self,
        payload: dict | None,
        tracked_ids: set[str],
        group_entries: list[AnimeSeriesEntry],
    ) -> list[dict]:
        if payload is None:
            return []

        group_ids = {entry.media_id for entry in group_entries}
        summaries = []
        blocks = [payload.get("series", {}), *payload.get("sections", [])]
        for block in blocks:
            entries = block.get("entries", [])
            if not entries:
                continue
            section_ids = {
                str(entry.get("media_id"))
                for entry in entries
                if entry.get("media_id") not in (None, "")
            }
            tracked_in_group = len(section_ids & group_ids)
            tracked_branches = len((section_ids & tracked_ids) - group_ids)
            summaries.append(
                {
                    "key": str(block.get("key") or ""),
                    "title": str(block.get("title") or "Related"),
                    "tracked_count": tracked_in_group,
                    "tracked_branch_count": tracked_branches,
                    "total_count": len(section_ids),
                },
            )
        return summaries

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
