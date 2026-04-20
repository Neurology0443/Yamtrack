"""Service-first MAL anime grouping engine for franchise sections."""

from __future__ import annotations

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder
from app.services.anime_franchise_ui_policies import UiPolicySuite
from app.services.anime_franchise_ui_policy_resolver import resolve_ui_policy_suite
from app.services.anime_franchise_ui_profiles import BaseUiProfile


class AnimeFranchiseService:
    """Compatibility facade that builds UI payload from canonical snapshot.

    The service is the main application path for UI policy-suite selection.
    """

    SERIES_LINE_KEY = "series_line"

    def __init__(
        self,
        graph_builder=None,
        *,
        ui_policy_suite: UiPolicySuite | None = None,
        ui_profile: BaseUiProfile | None = None,
        ui_profile_key: str | None = None,
        user=None,
        instance=None,
        ui_builder: AnimeFranchiseUiBuilder | None = None,
    ):
        self.snapshot_service = AnimeFranchiseSnapshotService(graph_builder=graph_builder)
        has_selector_args = any(
            arg is not None for arg in (ui_policy_suite, ui_profile, ui_profile_key)
        )
        if ui_builder is not None:
            # Injected builder is a hard override; ambiguous selector combos are forbidden.
            if has_selector_args:
                msg = (
                    "ui_builder is a full override and cannot be combined with "
                    "ui_policy_suite, ui_profile, or ui_profile_key"
                )
                raise ValueError(msg)
            self.ui_builder = ui_builder
        else:
            # Main path: centralize suite selection in the resolver, then run it
            # via the UI builder.
            resolved_suite = resolve_ui_policy_suite(
                ui_policy_suite=ui_policy_suite,
                ui_profile=ui_profile,
                ui_profile_key=ui_profile_key,
                user=user,
                instance=instance,
            )
            self.ui_builder = AnimeFranchiseUiBuilder(ui_policy_suite=resolved_suite)

    def build(self, media_id: str, *, refresh_cache: bool = False):
        snapshot = self.snapshot_service.build(
            str(media_id),
            refresh_cache=refresh_cache,
        )
        return self.ui_builder.build_view_model(snapshot)
