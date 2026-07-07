"""Compile rule-assigned candidates into ordered secondary sections.

This compiler is structural only: it groups candidates, resolves section
definitions, and orders the result. Placement decisions stay in rules.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from typing import TYPE_CHECKING

from .rule_types import CompiledSection, RuleContext, SectionDefinition

if TYPE_CHECKING:
    from .candidates import UiCandidate

COMPACTABLE_SECONDARY_BRANCH_SECTIONS = {
    "alternatives",
    "spin_offs",
    "related_series",
}

SECONDARY_BRANCH_CONTINUITY_RELATIONS = {
    "prequel",
    "sequel",
}

MIN_COMPACTED_BRANCH_SIZE = 2

SECONDARY_BRANCH_FAMILY_PRIORITY = (
    "alternative_version",
    "alternative_setting",
    "spin_off",
    "side_story",
    "parent_story",
    "full_story",
)


class LayoutCompiler:
    """Compile dynamic sections from candidate section keys and section definitions."""

    def compile(
        self,
        *,
        candidates: list[UiCandidate],
        context: RuleContext,
    ) -> list[CompiledSection]:
        """Return ordered compiled sections for visible candidates."""
        visible_candidates = [
            candidate
            for candidate in candidates
            if not candidate.hidden and candidate.section_key
        ]
        visible_candidates = self._compact_secondary_branches(
            visible_candidates,
            context,
        )

        grouped: dict[str, list[UiCandidate]] = defaultdict(list)
        for candidate in visible_candidates:
            grouped[candidate.section_key].append(candidate)

        section_defs = dict(context.sections)
        for section_key in grouped:
            section_defs.setdefault(
                section_key, self._fallback_section_definition(section_key)
            )

        sections: list[CompiledSection] = []
        for key, definition in section_defs.items():
            entries = grouped.get(key, [])
            entries = self._sort_entries(entries)
            if not entries and definition.hidden_if_empty:
                continue
            sections.append(
                CompiledSection(
                    key=definition.key,
                    title=definition.title,
                    order=definition.order,
                    hidden_if_empty=definition.hidden_if_empty,
                    metadata=dict(definition.metadata),
                    entries=entries,
                )
            )

        return sorted(sections, key=lambda section: (section.order, section.key))

    def _compact_secondary_branches(
        self,
        candidates: list[UiCandidate],
        context: RuleContext,
    ) -> list[UiCandidate]:
        """Collapse same-section secondary prequel/sequel branches."""
        candidates_by_section: dict[str, list[UiCandidate]] = defaultdict(list)
        for candidate in candidates:
            candidates_by_section[candidate.section_key or ""].append(candidate)

        compacted_by_id: set[str] = set()
        representatives_by_id: dict[str, UiCandidate] = {}
        for section_key in COMPACTABLE_SECONDARY_BRANCH_SECTIONS:
            section_candidates = candidates_by_section.get(section_key, [])
            if len(section_candidates) < MIN_COMPACTED_BRANCH_SIZE:
                continue
            for component in self._secondary_branch_components(
                section_candidates, context
            ):
                if len(component) < MIN_COMPACTED_BRANCH_SIZE:
                    continue
                representative = self._secondary_branch_representative(component)
                member_ids = self._secondary_branch_member_order(component, context)
                family = self._secondary_branch_family(component)
                representative.metadata["secondary_branch_collapsed"] = True
                representative.metadata["secondary_branch_member_ids"] = member_ids
                representative.metadata["secondary_branch_size"] = len(member_ids)
                representative.metadata["secondary_branch_relation_family"] = family
                compacted_by_id.update(candidate.media_id for candidate in component)
                representatives_by_id[representative.media_id] = representative

        if not compacted_by_id:
            return candidates

        return [
            candidate
            for candidate in candidates
            if candidate.media_id not in compacted_by_id
            or candidate.media_id in representatives_by_id
        ]

    def _secondary_branch_components(
        self,
        candidates: list[UiCandidate],
        context: RuleContext,
    ) -> list[list[UiCandidate]]:
        by_id = {candidate.media_id: candidate for candidate in candidates}
        candidate_ids = set(by_id)
        neighbors: dict[str, set[str]] = {media_id: set() for media_id in candidate_ids}
        for relation in getattr(context.snapshot, "all_normalized_relations", []):
            if relation.relation_type not in SECONDARY_BRANCH_CONTINUITY_RELATIONS:
                continue
            if (
                relation.source_media_id not in candidate_ids
                or relation.target_media_id not in candidate_ids
            ):
                continue
            neighbors[relation.source_media_id].add(relation.target_media_id)
            neighbors[relation.target_media_id].add(relation.source_media_id)

        components: list[list[UiCandidate]] = []
        seen: set[str] = set()
        for media_id in candidate_ids:
            if media_id in seen:
                continue
            stack = [media_id]
            component_ids: set[str] = set()
            seen.add(media_id)
            while stack:
                current = stack.pop()
                component_ids.add(current)
                for neighbor in neighbors[current]:
                    if neighbor in seen:
                        continue
                    seen.add(neighbor)
                    stack.append(neighbor)
            components.append([by_id[component_id] for component_id in component_ids])
        return components

    def _secondary_branch_member_order(
        self,
        candidates: list[UiCandidate],
        context: RuleContext,
    ) -> list[str]:
        by_id = {candidate.media_id: candidate for candidate in candidates}
        candidate_ids = set(by_id)
        outgoing: dict[str, set[str]] = {media_id: set() for media_id in candidate_ids}
        incoming_count = dict.fromkeys(candidate_ids, 0)

        for relation in getattr(context.snapshot, "all_normalized_relations", []):
            if relation.relation_type not in SECONDARY_BRANCH_CONTINUITY_RELATIONS:
                continue
            if (
                relation.source_media_id not in candidate_ids
                or relation.target_media_id not in candidate_ids
            ):
                continue
            if relation.relation_type == "sequel":
                before, after = relation.source_media_id, relation.target_media_id
            else:
                before, after = relation.target_media_id, relation.source_media_id
            if after in outgoing[before]:
                continue
            outgoing[before].add(after)
            incoming_count[after] += 1

        ready = deque(
            sorted(
                (media_id for media_id, count in incoming_count.items() if count == 0),
                key=lambda media_id: self._candidate_sort_key(by_id[media_id]),
            )
        )
        ordered: list[str] = []
        while ready:
            current = ready.popleft()
            ordered.append(current)
            for after in sorted(
                outgoing[current],
                key=lambda media_id: self._candidate_sort_key(by_id[media_id]),
            ):
                incoming_count[after] -= 1
                if incoming_count[after] == 0:
                    ready.append(after)
            ready = deque(
                sorted(
                    ready,
                    key=lambda media_id: self._candidate_sort_key(by_id[media_id]),
                )
            )

        remaining = [media_id for media_id in candidate_ids if media_id not in ordered]
        ordered.extend(
            sorted(
                remaining,
                key=lambda media_id: self._candidate_sort_key(by_id[media_id]),
            )
        )
        return ordered

    def _secondary_branch_representative(
        self, candidates: list[UiCandidate]
    ) -> UiCandidate:
        return min(
            candidates,
            key=lambda candidate: (
                self._candidate_family_rank(candidate),
                *self._candidate_sort_key(candidate),
            ),
        )

    def _secondary_branch_family(self, candidates: list[UiCandidate]) -> str:
        families = {
            family
            for candidate in candidates
            for family in self._candidate_families(candidate)
        }
        for family in SECONDARY_BRANCH_FAMILY_PRIORITY:
            if family in families:
                return family
        return ""

    def _candidate_family_rank(self, candidate: UiCandidate) -> int:
        families = self._candidate_families(candidate)
        ranks = [
            SECONDARY_BRANCH_FAMILY_PRIORITY.index(family)
            for family in families
            if family in SECONDARY_BRANCH_FAMILY_PRIORITY
        ]
        return min(ranks, default=len(SECONDARY_BRANCH_FAMILY_PRIORITY))

    @staticmethod
    def _candidate_families(candidate: UiCandidate) -> set[str]:
        families = set(candidate.relation_types)
        for origin in candidate.metadata.get("origins", []):
            relation_type = origin.get("relation_type")
            if relation_type:
                families.add(relation_type)
        return families

    def _candidate_sort_key(self, candidate: UiCandidate) -> tuple[date, int, str]:
        numeric_id, media_id = self._media_id_sort_value(candidate.media_id)
        return (candidate.start_date or date.max, numeric_id, media_id)

    @staticmethod
    def _media_id_sort_value(media_id: str) -> tuple[int, str]:
        try:
            return (int(media_id), media_id)
        except ValueError:
            return (10**18, media_id)

    @staticmethod
    def _fallback_section_definition(section_key: str) -> SectionDefinition:
        """Build default section metadata for keys without definitions."""
        return SectionDefinition(
            key=section_key,
            title=section_key.replace("_", " ").title(),
        )

    @staticmethod
    def _sort_entries(entries: list[UiCandidate]) -> list[UiCandidate]:
        """Apply generic metadata-driven structural sorting."""
        if not entries:
            return entries

        indexed_entries = list(enumerate(entries))
        has_rank = any(
            entry.metadata.get("section_sort_rank") is not None
            for _, entry in indexed_entries
        )
        if not has_rank:
            return entries

        return [
            entry
            for _, entry in sorted(
                indexed_entries,
                key=lambda item: (
                    item[1].metadata.get("section_sort_rank", float("inf")),
                    item[0],
                ),
            )
        ]
