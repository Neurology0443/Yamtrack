"""Centralize UI policy-suite selection for anime franchise rendering."""

from __future__ import annotations

from app.services.anime_franchise_ui_policies import UiPolicySuite
from app.services.anime_franchise_ui_profiles import (
    BaseUiProfile,
    build_policy_suite_from_legacy_profile,
    get_ui_profile,
)

# Centralized system default for this phase. Future user/instance config can
# override this in one place without spreading selection logic around the app.
SYSTEM_DEFAULT_UI_PROFILE_KEY = "default"


def resolve_ui_policy_suite(
    *,
    ui_policy_suite: UiPolicySuite | None = None,
    ui_profile: BaseUiProfile | None = None,
    ui_profile_key: str | None = None,
    user=None,
    instance=None,
) -> UiPolicySuite:
    """Resolve a ``UiPolicySuite`` with an explicit, stable priority order.

    Priority (highest -> lowest):
    1) explicit ``ui_policy_suite`` (tests/debug/injection path)
    2) explicit legacy ``ui_profile`` (adapted to a suite)
    3) explicit legacy ``ui_profile_key`` (resolved then adapted)
    4) centralized system default profile key

    ``user``/``instance`` are accepted as extension points for future config
    layers; they are intentionally unused in this phase.
    """

    # Reserved for future per-user/per-instance policy selection.
    del user, instance

    if ui_policy_suite is not None:
        return ui_policy_suite

    if ui_profile is not None:
        # Legacy profile compatibility is still supported during migration.
        return build_policy_suite_from_legacy_profile(ui_profile)

    # Use the system default only when no key is provided at all; invalid/empty
    # explicit keys must fail loudly via get_ui_profile(...).
    resolved_profile_key = (
        SYSTEM_DEFAULT_UI_PROFILE_KEY if ui_profile_key is None else ui_profile_key
    )
    return build_policy_suite_from_legacy_profile(get_ui_profile(resolved_profile_key))


__all__ = ["SYSTEM_DEFAULT_UI_PROFILE_KEY", "resolve_ui_policy_suite"]
