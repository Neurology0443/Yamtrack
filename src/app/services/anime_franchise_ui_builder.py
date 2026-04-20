"""Build UI sections from a snapshot + shared franchise candidate projection."""

from __future__ import annotations

from collections import defaultdict

from app.services.anime_franchise_candidate_projection import build_franchise_candidates
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot
from app.services.anime_franchise_types import (
    AnimeFranchiseCandidate,
    AnimeFranchiseSectionRule,
    AnimeFranchiseSectionView,
    AnimeFranchiseViewModel,
)
from app.services.anime_franchise_ui_policies import BaseUiPolicy, UiPolicyStage, UiPolicySuite
from app.services.anime_franchise_ui_profiles import (
    BaseUiProfile,
    build_policy_suite_from_legacy_profile,
    get_ui_profile,
)
from app.services.anime_franchise_ui_rules import get_section_rules


class AnimeFranchiseUiBuilder:
    """Build UI grouping from the canonical franchise snapshot.

    The builder executes a ``UiPolicySuite`` in four stages on top of stable
    ``ui_rules`` classification:
    1) visibility
    2) section_target
    3) sort
    4) section_title

    Historical UI profiles are still supported by adapting them to policy suites.
    """

    def __init__(
        self,
        *,
        ui_policy_suite: UiPolicySuite | None = None,
        ui_profile: BaseUiProfile | None = None,
        ui_profile_key: str = "default",
    ):
        if ui_policy_suite is not None:
            self.ui_policy_suite = ui_policy_suite
        elif ui_profile is not None:
            self.ui_policy_suite = build_policy_suite_from_legacy_profile(ui_profile)
        else:
            self.ui_policy_suite = build_policy_suite_from_legacy_profile(get_ui_profile(ui_profile_key))
        self.policies_by_stage = self.ui_policy_suite.grouped_by_stage()

    def build_view_model(self, snapshot: AnimeFranchiseSnapshot) -> AnimeFranchiseViewModel:
        """Assemble the UI view model from snapshot data and shared candidates."""
        candidate_map = build_franchise_candidates(snapshot)
        grouped_sections = self._group_candidates_with_policies(list(candidate_map.values()))

        ordered_sections = []
        rules = get_section_rules()
        title_policies = self.policies_by_stage.get(UiPolicyStage.SECTION_TITLE, ())
        for rule in rules:
            if rule.key == "ignored":
                continue

            section_candidates = grouped_sections.get(rule.key, [])
            section_title = self._apply_title_policies(
                section_key=rule.key,
                default_title=rule.title,
                candidates=section_candidates,
                policies=title_policies,
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

    def _group_candidates_with_policies(
        self,
        candidates: list[AnimeFranchiseCandidate],
    ) -> dict[str, list[AnimeFranchiseCandidate]]:
        """Classify with base rules, then apply staged policy suite logic."""

        rules = get_section_rules()
        known_section_keys = {rule.key for rule in rules}
        rules_by_key = {rule.key: rule for rule in rules}
        visibility_policies = self.policies_by_stage.get(UiPolicyStage.VISIBILITY, ())
        target_policies = self.policies_by_stage.get(UiPolicyStage.SECTION_TARGET, ())
        sort_policies = self.policies_by_stage.get(UiPolicyStage.SORT, ())

        sections: dict[str, list[AnimeFranchiseCandidate]] = defaultdict(list)
        for candidate in candidates:
            default_section_key = self._classify_candidate(candidate, rules)
            if default_section_key is None:
                continue
            if not self._is_candidate_visible(candidate, visibility_policies):
                continue

            target_section_key = self._resolve_target_section_key(
                candidate=candidate,
                default_section_key=default_section_key,
                known_section_keys=known_section_keys,
                policies=target_policies,
            )
            sections[target_section_key].append(candidate)

        sorted_sections: dict[str, list[AnimeFranchiseCandidate]] = {}
        for section_key, section_candidates in sections.items():
            section_rule = rules_by_key.get(section_key)
            if section_rule is not None:
                section_candidates.sort(
                    key=lambda candidate: self._candidate_sort_key(candidate, section_rule.sort_mode)
                )
            current_candidates = list(section_candidates)
            for policy in sort_policies:
                current_candidates = self._validated_policy_candidates(
                    section_key=section_key,
                    candidates=policy.sort_section_candidates(section_key, current_candidates),
                    original_candidates=current_candidates,
                    policy=policy,
                )
            sorted_sections[section_key] = current_candidates

        return sorted_sections

    @staticmethod
    def _is_candidate_visible(
        candidate: AnimeFranchiseCandidate,
        policies: tuple[BaseUiPolicy, ...],
    ) -> bool:
        for policy in policies:
            if not policy.is_candidate_visible(candidate):
                return False
        return True

    @staticmethod
    def _resolve_target_section_key(
        *,
        candidate: AnimeFranchiseCandidate,
        default_section_key: str,
        known_section_keys: set[str],
        policies: tuple[BaseUiPolicy, ...],
    ) -> str:
        current_section_key = default_section_key
        for policy in policies:
            current_section_key = policy.target_section_key(candidate, current_section_key)
        # Unknown section targets should never create new sections; fallback to
        # the stable UI-rules default classification.
        if current_section_key not in known_section_keys:
            return default_section_key
        return current_section_key

    @staticmethod
    def _apply_title_policies(
        *,
        section_key: str,
        default_title: str,
        candidates: list[AnimeFranchiseCandidate],
        policies: tuple[BaseUiPolicy, ...],
    ) -> str:
        title = default_title
        for policy in policies:
            next_title = policy.section_title(section_key, title, candidates)
            if isinstance(next_title, str) and next_title.strip():
                title = next_title
        return title

    def _classify_candidate(
        self,
        candidate: AnimeFranchiseCandidate,
        rules: list[AnimeFranchiseSectionRule],
    ) -> str | None:
        for rule in rules:
            if self._matches_rule(candidate, rule):
                return rule.key
        return None

    def _validated_policy_candidates(
        self,
        *,
        section_key: str,
        candidates,
        original_candidates: list[AnimeFranchiseCandidate],
        policy: BaseUiPolicy,
    ) -> list[AnimeFranchiseCandidate]:
        """Validate sort-stage policy return contract for one section."""
        policy_name = policy.source_name
        if candidates is None:
            return []
        if isinstance(candidates, list):
            validated_candidates = candidates
        elif isinstance(candidates, tuple):
            validated_candidates = list(candidates)
        else:
            msg = (
                f"UI policy/profile '{policy_name}' returned invalid candidates for section "
                f"'{section_key}': expected None, list[AnimeFranchiseCandidate], or "
                f"tuple[AnimeFranchiseCandidate, ...], got {type(candidates).__name__}"
            )
            raise TypeError(msg)

        for idx, candidate in enumerate(validated_candidates):
            if not isinstance(candidate, AnimeFranchiseCandidate):
                msg = (
                    f"UI policy/profile '{policy_name}' returned invalid candidate at index "
                    f"{idx} for section '{section_key}': expected AnimeFranchiseCandidate, "
                    f"got {type(candidate).__name__}"
                )
                raise TypeError(msg)

        original_candidate_ids = {id(candidate) for candidate in original_candidates}
        seen_candidate_ids: set[int] = set()
        for candidate in validated_candidates:
            candidate_identity = id(candidate)
            # Sorting policies may reorder/drop entries, but must keep the exact
            # candidate objects from this section (no foreign/rebuilt objects).
            if candidate_identity not in original_candidate_ids:
                msg = (
                    f"UI policy/profile '{policy_name}' returned candidate with media_id "
                    f"'{candidate.media_id}' for section '{section_key}' that was not "
                    "one of the original input candidate objects"
                )
                raise TypeError(msg)
            if candidate_identity in seen_candidate_ids:
                msg = (
                    f"UI policy/profile '{policy_name}' returned duplicate candidate with media_id "
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
