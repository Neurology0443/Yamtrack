"""UI profile for MAL anime franchise grouping."""

from __future__ import annotations

from collections import defaultdict
import re

from app.services.anime_franchise_rules import get_section_rules
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import (
    AnimeFranchiseCandidate,
    AnimeFranchiseSectionRule,
    AnimeFranchiseSectionView,
    AnimeFranchiseViewModel,
)


class AnimeFranchiseUiProfile:
    """Render UI grouping from the canonical snapshot."""

    SERIES_LINE_KEY = "series_line"
    _SEPARATOR_PATTERN = re.compile(r"[-:/]+")
    _WHITESPACE_PATTERN = re.compile(r"\s+")
    _SEASON_PATTERNS = (
        re.compile(r"\bseason\s+([a-z0-9]+)\b"),
        re.compile(r"\b([a-z0-9]+)\s+season\b"),
    )
    _PART_PATTERNS = (
        re.compile(r"\bpart\s+([a-z0-9]+)\b"),
        re.compile(r"\b([a-z0-9]+)\s+part\b"),
        re.compile(r"\bcour\s+([a-z0-9]+)\b"),
        re.compile(r"\b([a-z0-9]+)\s+cour\b"),
    )
    _ORDINAL_DIGIT_PATTERN = re.compile(r"^(\d+)(st|nd|rd|th)$")
    _ROMAN_PATTERN = re.compile(r"[ivxlcdm]+")
    _TEXT_NUMBERS = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
    }

    def build_view_model(self, snapshot: AnimeFranchiseSnapshot) -> AnimeFranchiseViewModel:
        series_line_ids = {node.media_id for node in snapshot.series_line}
        candidate_map = self._build_candidates(snapshot, series_line_ids)
        grouped_sections = self._classify_candidates(list(candidate_map.values()))

        ordered_sections = []
        for rule in get_section_rules():
            if rule.key == "ignored":
                continue

            section_entries = [
                self._node_to_entry(candidate_map[item.media_id], snapshot.nodes_by_media_id[item.media_id])
                for item in grouped_sections[rule.key]
            ]
            ordered_sections.append(
                AnimeFranchiseSectionView(
                    key=rule.key,
                    title=rule.title,
                    entries=section_entries,
                    visible_in_ui=rule.visible_in_ui,
                    hidden_if_empty=rule.hidden_if_empty,
                )
            )

        series_entries = self._build_series_line_entries(snapshot)

        return AnimeFranchiseViewModel(
            root_media_id=snapshot.root_node.media_id,
            display_title=snapshot.root_node.title,
            series_line_entries=series_entries,
            sections=ordered_sections,
        )

    def _build_series_line_entries(self, snapshot: AnimeFranchiseSnapshot) -> list[dict]:
        return [
            self._node_to_series_line_entry(
                node,
                is_current=node.media_id == snapshot.root_node.media_id,
            )
            for node in snapshot.series_line
        ]

    def _build_candidates(
        self,
        snapshot: AnimeFranchiseSnapshot,
        series_line_ids: set[str],
    ) -> dict[str, AnimeFranchiseCandidate]:
        candidates: dict[str, AnimeFranchiseCandidate] = {}
        line_index_map = {node.media_id: idx for idx, node in enumerate(snapshot.series_line)}

        for relation in snapshot.direct_candidates:
            target_id = relation.target_media_id
            if target_id in series_line_ids:
                continue

            target_node = snapshot.nodes_by_media_id[target_id]
            linked_id = relation.source_media_id if snapshot.has_series_line else snapshot.fallback_anchor_media_id
            candidate = AnimeFranchiseCandidate(
                media_id=target_node.media_id,
                title=target_node.title,
                image=target_node.image,
                source=target_node.source,
                media_type=target_node.media_type,
                start_date=target_node.start_date,
                relation_type=relation.relation_type,
                is_current=target_node.media_id == snapshot.root_node.media_id,
                is_direct_from_series_line=True,
                linked_series_line_media_id=linked_id,
                linked_series_line_index=(line_index_map.get(linked_id) if snapshot.has_series_line else 0),
            )
            existing = candidates.get(candidate.media_id)
            if existing is None or self._candidate_sort_key(candidate, "continuity_extras") < self._candidate_sort_key(existing, "continuity_extras"):
                candidates[candidate.media_id] = candidate

        return candidates

    def _classify_candidates(self, candidates: list[AnimeFranchiseCandidate]) -> dict[str, list[AnimeFranchiseCandidate]]:
        sections: dict[str, list[AnimeFranchiseCandidate]] = defaultdict(list)
        rules = get_section_rules()

        for candidate in candidates:
            for rule in rules:
                if self._matches_rule(candidate, rule):
                    sections[rule.key].append(candidate)
                    break

        rules_by_key = {rule.key: rule for rule in rules}
        for section_key, section_candidates in sections.items():
            primary_rule = rules_by_key[section_key]
            section_candidates.sort(key=lambda candidate: self._candidate_sort_key(candidate, primary_rule.sort_mode))

        return sections

    def _matches_rule(self, candidate: AnimeFranchiseCandidate, rule: AnimeFranchiseSectionRule) -> bool:  # noqa: PLR0911
        if rule.predicate and not rule.predicate(candidate):
            return False
        if rule.include_relation_types and candidate.relation_type not in rule.include_relation_types:
            return False
        if candidate.relation_type in rule.exclude_relation_types:
            return False
        if rule.include_media_types and candidate.media_type not in rule.include_media_types:
            return False
        if candidate.media_type in rule.exclude_media_types:
            return False
        if rule.direct_from_series_line_only and not candidate.is_direct_from_series_line:
            return False
        return not (not rule.allow_indirect_candidates and not candidate.is_direct_from_series_line)

    def _node_to_entry(self, candidate: AnimeFranchiseCandidate, node) -> dict:
        entry = self._node_to_entry_from_node(node, is_current=candidate.is_current)
        entry.update(
            {
                "relation_type": candidate.relation_type,
                "linked_series_line_media_id": candidate.linked_series_line_media_id,
                "linked_series_line_index": candidate.linked_series_line_index,
            }
        )
        return entry

    def _node_to_series_line_entry(self, node, *, is_current: bool) -> dict:
        entry = self._node_to_entry_from_node(node, is_current=is_current)
        entry["display_series_line_label"] = self._derive_series_line_display_label(node.title)
        return entry

    @staticmethod
    def _node_to_entry_from_node(node, *, is_current: bool) -> dict:
        return {
            "media_id": node.media_id,
            "title": node.title,
            "image": node.image,
            "source": node.source,
            "media_type": "anime",
            "anime_media_type": node.media_type,
            "relation_type": None,
            "linked_series_line_media_id": None,
            "linked_series_line_index": None,
            "is_current": is_current,
            "display_series_line_label": None,
        }

    def _derive_series_line_display_label(self, title: str) -> str | None:
        parsed = self._parse_series_line_title(title)
        if parsed is None:
            return None
        season_number, part_number = parsed
        if part_number is None:
            return f"Season {season_number}"
        return f"Season {season_number} Part {part_number}"

    def _parse_series_line_title(self, title: str) -> tuple[int, int | None] | None:
        normalized_title = self._normalize_series_title(title)
        season_number = self._extract_season_number(normalized_title)
        if season_number is None:
            return None
        part_number = self._extract_part_number(normalized_title)
        return season_number, part_number

    @staticmethod
    def _normalize_series_title(title: str) -> str:
        normalized = AnimeFranchiseUiProfile._SEPARATOR_PATTERN.sub(" ", title.lower())
        return AnimeFranchiseUiProfile._WHITESPACE_PATTERN.sub(" ", normalized).strip()

    def _extract_season_number(self, normalized_title: str) -> int | None:
        for pattern in self._SEASON_PATTERNS:
            match = pattern.search(normalized_title)
            if not match:
                continue
            return self._token_to_int(match.group(1))
        return None

    def _extract_part_number(self, normalized_title: str) -> int | None:
        for pattern in self._PART_PATTERNS:
            match = pattern.search(normalized_title)
            if not match:
                continue
            parsed = self._token_to_int(match.group(1))
            if parsed is not None:
                return parsed
        return None

    def _token_to_int(self, token: str) -> int | None:
        token = token.strip().lower()
        if token.isdigit():
            return int(token)

        ordinal_match = self._ORDINAL_DIGIT_PATTERN.match(token)
        if ordinal_match:
            return int(ordinal_match.group(1))

        roman = self._roman_to_int(token)
        if roman is not None:
            return roman

        return self._TEXT_NUMBERS.get(token)

    @staticmethod
    def _roman_to_int(token: str) -> int | None:
        if not token or not AnimeFranchiseUiProfile._ROMAN_PATTERN.fullmatch(token):
            return None

        values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
        total = 0
        previous = 0
        for char in reversed(token):
            value = values[char]
            if value < previous:
                total -= value
            else:
                total += value
                previous = value
        return total if total > 0 else None

    def _candidate_sort_key(self, candidate: AnimeFranchiseCandidate, sort_mode: str) -> tuple:
        linked_index = candidate.linked_series_line_index if candidate.linked_series_line_index is not None else 10_000
        if sort_mode == "continuity_extras":
            relation_rank = 0 if candidate.relation_type == "prequel" else 1
            return (linked_index, relation_rank, self._date_value(candidate.start_date), int(candidate.media_id))
        return (linked_index, self._date_value(candidate.start_date), int(candidate.media_id))

    @staticmethod
    def _date_value(start_date) -> str:
        return start_date.isoformat() if start_date else "9999-12-31"
