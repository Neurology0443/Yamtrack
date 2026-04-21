"""Service-first MAL anime grouping engine for franchise sections."""

from __future__ import annotations

from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline


class AnimeFranchiseService:
    """Compatibility facade that builds UI payload from canonical snapshot."""

    SERIES_LINE_KEY = "series_line"

    def __init__(self, graph_builder=None):
        self.snapshot_service = AnimeFranchiseSnapshotService(graph_builder=graph_builder)
        self.ui_pipeline = AnimeFranchiseUiPipeline()

    def build(self, media_id: str, *, refresh_cache: bool = False):
        snapshot = self.snapshot_service.build(
            str(media_id),
            refresh_cache=refresh_cache,
        )
        return self.ui_pipeline.run(snapshot)
