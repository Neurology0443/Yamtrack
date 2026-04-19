"""UI builder that projects a franchise snapshot into a renderable view model."""

from __future__ import annotations

from collections import defaultdict

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import (
    AnimeFranchiseCandidate,
    AnimeFranchiseSectionRule,
    AnimeFranchiseSectionView,
    AnimeFranchiseViewModel,
)
from app.services.anime_franchise_ui_profiles import BaseUiProfile, get_ui_profile
from app.services.anime_franchise_ui_rules import get_section_rules


class AnimeFranchiseUiBuilder:
    """Build UI grouping from the canonical franchise snapshot.

    Flow:
    1) build candidates
    2) classify via common UI rules
    3) apply profile visibility
    4) apply profile section reassignment
    5) apply profile section sorting
    6) apply profile section title policy
    7) assemble ``AnimeFranchiseViewModel``
    """

    SERIES_LINE_KEY = "series_line"

    def __init__(self, *, ui_profile: BaseUiProfile | None = None, ui_profile_key: str = "default"):
        self.ui_profile = ui_profile or get_ui_profile(ui_profile_key)

    def build_view_model(self, snapshot: AnimeFranchiseSnapshot) -> AnimeFranchiseViewModel:
        series_line_ids = {node.media_id for node in snapshot.series_line}
        candidate_map = self._build_candidates(snapshot, series_line_ids)
        grouped_sections = self._group_candidates_with_profile(list(candidate_map.values()))

        ordered_sections = []
        for rule in get_section_rules():
            if rule.key == "ignored":
                continue

            section_candidates = grouped_sections.get(rule.key, [])
            section_title = self.ui_profile.section_title(
                rule.key,
                rule.title,
                section_candidates,
            )
            section_entries = [
                self._node_to_entry(candidate_map[item.media_id], snapshot.nodes_by_media_id[item.media_id])
                for item in section_candidates
            ]
            ordered_sections.append(
                AnimeFranchiseSectionView(
                    key=rule.key,
                    title=section_title,
                    entries=section_entries,
                    visible_in_ui=rule.visible_in_ui,
                    hidden_if_empty=rule.hidden_if_empty,
                )
            )

        series_entries = [
            self._node_to_entry_from_node(node, is_current=node.media_id == snapshot.root_node.media_id)
            for node in snapshot.series_line
        ]

        return AnimeFranchiseViewModel(
            root_media_id=snapshot.root_node.media_id,
            display_title=snapshot.root_node.title,
            series_line_entries=series_entries,
            sections=ordered_sections,
        )

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

    def _group_candidates_with_profile(
        self,
        candidates: list[AnimeFranchiseCandidate],
    ) -> dict[str, list[AnimeFranchiseCandidate]]:
        """Classify candidates with base rules, then apply profile UI policy.

        If a profile returns an unknown section key, fallback is the default
        section from common rule classification.
        """

        rules = get_section_rules()
        known_section_keys = {rule.key for rule in rules}
        rules_by_key = {rule.key: rule for rule in rules}

        sections: dict[str, list[AnimeFranchiseCandidate]] = defaultdict(list)
        for candidate in candidates:
            default_section_key = self._classify_candidate(candidate, rules)
            if default_section_key is None:
                continue
            if not self.ui_profile.is_candidate_visible(candidate):
                continue

            target_section_key = self.ui_profile.target_section_key(candidate, default_section_key)
            if target_section_key not in known_section_keys:
                target_section_key = default_section_key
            sections[target_section_key].append(candidate)

        sorted_sections: dict[str, list[AnimeFranchiseCandidate]] = {}
        for section_key, section_candidates in sections.items():
            section_rule = rules_by_key.get(section_key)
            if section_rule is not None:
                section_candidates.sort(
                    key=lambda candidate: self._candidate_sort_key(candidate, section_rule.sort_mode)
                )
            base_sorted_candidates = list(section_candidates)
            sorted_sections[section_key] = self._validated_profile_candidates(
                section_key=section_key,
                candidates=self.ui_profile.sort_section_candidates(section_key, section_candidates),
                original_candidates=base_sorted_candidates,
            )

        return sorted_sections

    def _classify_candidate(
        self,
        candidate: AnimeFranchiseCandidate,
        rules: list[AnimeFranchiseSectionRule],
    ) -> str | None:
        for rule in rules:
            if self._matches_rule(candidate, rule):
                return rule.key
        return None

    def _validated_profile_candidates(
        self,
        *,
        section_key: str,
        candidates,
        original_candidates: list[AnimeFranchiseCandidate],
    ) -> list[AnimeFranchiseCandidate]:
        """Validate profile sort hook return contract for one section."""
        profile_name = self.ui_profile.__class__.__name__
        if candidates is None:
            return []
        if isinstance(candidates, list):
            validated_candidates = candidates
        elif isinstance(candidates, tuple):
            validated_candidates = list(candidates)
        else:
            msg = (
                f"UI profile '{profile_name}' returned invalid candidates for section "
                f"'{section_key}': expected None, list[AnimeFranchiseCandidate], or "
                f"tuple[AnimeFranchiseCandidate, ...], got {type(candidates).__name__}"
            )
            raise TypeError(msg)

        for idx, candidate in enumerate(validated_candidates):
            if not isinstance(candidate, AnimeFranchiseCandidate):
                msg = (
                    f"UI profile '{profile_name}' returned invalid candidate at index "
                    f"{idx} for section '{section_key}': expected AnimeFranchiseCandidate, "
                    f"got {type(candidate).__name__}"
                )
                raise TypeError(msg)

        original_candidate_ids = {id(candidate) for candidate in original_candidates}
        seen_candidate_ids: set[int] = set()
        for candidate in validated_candidates:
            candidate_identity = id(candidate)
            if candidate_identity not in original_candidate_ids:
                msg = (
                    f"UI profile '{profile_name}' returned candidate with media_id "
                    f"'{candidate.media_id}' for section '{section_key}' that was not "
                    "one of the original input candidate objects"
                )
                raise TypeError(msg)
            if candidate_identity in seen_candidate_ids:
                msg = (
                    f"UI profile '{profile_name}' returned duplicate candidate with media_id "
                    f"'{candidate.media_id}' for section '{section_key}'"
                )
                raise TypeError(msg)
            seen_candidate_ids.add(candidate_identity)
        return validated_candidates

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
        }

    def _candidate_sort_key(self, candidate: AnimeFranchiseCandidate, sort_mode: str) -> tuple:
        linked_index = candidate.linked_series_line_index if candidate.linked_series_line_index is not None else 10_000
        if sort_mode == "continuity_extras":
            relation_rank = 0 if candidate.relation_type == "prequel" else 1
            return (linked_index, relation_rank, self._date_value(candidate.start_date), int(candidate.media_id))
        return (linked_index, self._date_value(candidate.start_date), int(candidate.media_id))

    @staticmethod
    def _date_value(start_date) -> str:
        return start_date.isoformat() if start_date else "9999-12-31"
