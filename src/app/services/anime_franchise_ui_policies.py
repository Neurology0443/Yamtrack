"""Composable UI policies executed in stages by ``AnimeFranchiseUiBuilder``."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING

from app.services.anime_franchise_types import AnimeFranchiseCandidate

if TYPE_CHECKING:
    from app.services.anime_franchise_ui_profiles import BaseUiProfile


class UiPolicyStage(StrEnum):
    """Execution stages for the UI policy engine."""

    VISIBILITY = "visibility"
    SECTION_TARGET = "section_target"
    SORT = "sort"
    SECTION_TITLE = "section_title"


class BaseUiPolicy:
    """Atomic policy unit applied during one stage of UI construction."""

    key = "base"
    stage: UiPolicyStage = UiPolicyStage.VISIBILITY
    priority = 100

    @property
    def source_name(self) -> str:
        """Human-readable source used in validation errors."""

        return self.__class__.__name__

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        return True

    def target_section_key(
        self,
        candidate: AnimeFranchiseCandidate,
        current_section_key: str,
    ) -> str:
        return current_section_key

    def sort_section_candidates(
        self,
        section_key: str,
        candidates: list[AnimeFranchiseCandidate],
    ):
        return candidates

    def section_title(
        self,
        section_key: str,
        current_title: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> str:
        return current_title


@dataclass(frozen=True)
class UiPolicySpec:
    """Lightweight future-facing policy description container."""

    key: str
    priority: int | None = None
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UiPolicySuite:
    """Ordered policy collection used by the UI builder."""

    policies: tuple[BaseUiPolicy, ...] = ()

    def grouped_by_stage(self) -> dict[UiPolicyStage, tuple[BaseUiPolicy, ...]]:
        grouped: dict[UiPolicyStage, list[BaseUiPolicy]] = {}
        for policy in self.policies:
            grouped.setdefault(policy.stage, []).append(policy)

        return {
            stage: tuple(sorted(stage_policies, key=lambda item: item.priority))
            for stage, stage_policies in grouped.items()
        }

    def policies_for_stage(self, stage: UiPolicyStage) -> tuple[BaseUiPolicy, ...]:
        return self.grouped_by_stage().get(stage, ())


class HideRelationTypesPolicy(BaseUiPolicy):
    key = "hide_relation_types"
    stage = UiPolicyStage.VISIBILITY

    def __init__(self, relation_types: frozenset[str], *, priority: int = 100):
        self.relation_types = frozenset(relation_types)
        self.priority = priority

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        return candidate.relation_type not in self.relation_types


class HideMediaTypesPolicy(BaseUiPolicy):
    key = "hide_media_types"
    stage = UiPolicyStage.VISIBILITY

    def __init__(self, media_types: frozenset[str], *, priority: int = 100):
        self.media_types = frozenset(media_types)
        self.priority = priority

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        return candidate.media_type not in self.media_types


class HideTitlesPolicy(BaseUiPolicy):
    key = "hide_titles"
    stage = UiPolicyStage.VISIBILITY

    def __init__(self, titles: frozenset[str], *, priority: int = 100):
        self.hidden_titles = frozenset(titles)
        self.priority = priority

    @staticmethod
    def _normalize_title(title: str) -> str:
        return title.strip().casefold()

    @cached_property
    def normalized_hidden_titles(self) -> frozenset[str]:
        return frozenset(self._normalize_title(title) for title in self.hidden_titles)

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        return self._normalize_title(candidate.title) not in self.normalized_hidden_titles


class LegacyProfileVisibilityPolicy(BaseUiPolicy):
    key = "legacy_profile_visibility"
    stage = UiPolicyStage.VISIBILITY

    def __init__(self, legacy_profile: BaseUiProfile, *, priority: int = 100):
        self.legacy_profile = legacy_profile
        self.priority = priority

    @property
    def source_name(self) -> str:
        # Keep legacy profile names in errors for backward-friendly diagnostics.
        return self.legacy_profile.__class__.__name__

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        return self.legacy_profile.is_candidate_visible(candidate)


class LegacyProfileSectionTargetPolicy(BaseUiPolicy):
    key = "legacy_profile_section_target"
    stage = UiPolicyStage.SECTION_TARGET

    def __init__(self, legacy_profile: BaseUiProfile, *, priority: int = 100):
        self.legacy_profile = legacy_profile
        self.priority = priority

    @property
    def source_name(self) -> str:
        return self.legacy_profile.__class__.__name__

    def target_section_key(self, candidate: AnimeFranchiseCandidate, current_section_key: str) -> str:
        return self.legacy_profile.target_section_key(candidate, current_section_key)


class LegacyProfileSortPolicy(BaseUiPolicy):
    key = "legacy_profile_sort"
    stage = UiPolicyStage.SORT

    def __init__(self, legacy_profile: BaseUiProfile, *, priority: int = 100):
        self.legacy_profile = legacy_profile
        self.priority = priority

    @property
    def source_name(self) -> str:
        return self.legacy_profile.__class__.__name__

    def sort_section_candidates(self, section_key: str, candidates: list[AnimeFranchiseCandidate]):
        return self.legacy_profile.sort_section_candidates(section_key, candidates)


class LegacyProfileSectionTitlePolicy(BaseUiPolicy):
    key = "legacy_profile_section_title"
    stage = UiPolicyStage.SECTION_TITLE

    def __init__(self, legacy_profile: BaseUiProfile, *, priority: int = 100):
        self.legacy_profile = legacy_profile
        self.priority = priority

    @property
    def source_name(self) -> str:
        return self.legacy_profile.__class__.__name__

    def section_title(
        self,
        section_key: str,
        current_title: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> str:
        return self.legacy_profile.section_title(section_key, current_title, candidates)


__all__ = [
    "BaseUiPolicy",
    "HideMediaTypesPolicy",
    "HideRelationTypesPolicy",
    "HideTitlesPolicy",
    "LegacyProfileVisibilityPolicy",
    "LegacyProfileSectionTargetPolicy",
    "LegacyProfileSectionTitlePolicy",
    "LegacyProfileSortPolicy",
    "UiPolicySpec",
    "UiPolicyStage",
    "UiPolicySuite",
]
