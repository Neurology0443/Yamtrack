"""Minimal registry/helpers for constructing anime franchise UI policies."""

from __future__ import annotations

from collections.abc import Callable

from app.services.anime_franchise_ui_policies import (
    BaseUiPolicy,
    HideMediaTypesPolicy,
    HideRelationTypesPolicy,
    HideTitlesPolicy,
    UiPolicySpec,
    UiPolicySuite,
)

PolicyFactory = Callable[[UiPolicySpec], BaseUiPolicy]


def _priority(spec: UiPolicySpec) -> int:
    return spec.priority if spec.priority is not None else 100


def _build_hide_relation_types(spec: UiPolicySpec) -> BaseUiPolicy:
    """Build ``hide_relation_types`` policy (expects ``relation_types`` iterable)."""
    return HideRelationTypesPolicy(
        relation_types=frozenset(spec.params.get("relation_types", ())),
        priority=_priority(spec),
    )


def _build_hide_media_types(spec: UiPolicySpec) -> BaseUiPolicy:
    """Build ``hide_media_types`` policy (expects ``media_types`` iterable)."""
    return HideMediaTypesPolicy(
        media_types=frozenset(spec.params.get("media_types", ())),
        priority=_priority(spec),
    )


def _build_hide_titles(spec: UiPolicySpec) -> BaseUiPolicy:
    """Build ``hide_titles`` policy (expects ``titles`` iterable)."""
    return HideTitlesPolicy(
        titles=frozenset(spec.params.get("titles", ())),
        priority=_priority(spec),
    )


POLICY_REGISTRY: dict[str, PolicyFactory] = {
    HideRelationTypesPolicy.key: _build_hide_relation_types,
    HideMediaTypesPolicy.key: _build_hide_media_types,
    HideTitlesPolicy.key: _build_hide_titles,
}


def build_policy(policy_spec: UiPolicySpec) -> BaseUiPolicy:
    """Instantiate a generic policy from a lightweight spec."""

    if policy_spec.key not in POLICY_REGISTRY:
        msg = f"Unsupported UI policy '{policy_spec.key}'"
        raise ValueError(msg)

    return POLICY_REGISTRY[policy_spec.key](policy_spec)


def build_policy_suite(policy_specs: list[UiPolicySpec] | tuple[UiPolicySpec, ...]) -> UiPolicySuite:
    """Build an ordered ``UiPolicySuite`` from policy specs."""

    return UiPolicySuite(policies=tuple(build_policy(policy_spec) for policy_spec in policy_specs))


__all__ = ["POLICY_REGISTRY", "build_policy", "build_policy_suite"]
