"""Service-first MAL anime grouping engine for franchise sections."""

from __future__ import annotations

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder


class AnimeFranchiseService:
    """Compatibility facade that builds UI payload from canonical snapshot."""

    SERIES_LINE_KEY = "series_line"

    def __init__(
        self,
        graph_builder=None,
        *,
        ui_profile_key: str = "default",
        ui_builder: AnimeFranchiseUiBuilder | None = None,
    ):
        self.snapshot_service = AnimeFranchiseSnapshotService(graph_builder=graph_builder)
        self.ui_builder = ui_builder or AnimeFranchiseUiBuilder(ui_profile_key=ui_profile_key)

    def build(self, media_id: str, *, refresh_cache: bool = False):
        snapshot = self.snapshot_service.build(
            str(media_id),
            refresh_cache=refresh_cache,
        )
        return self.ui_builder.build_view_model(snapshot)
