"""Public entrypoint for the anime franchise UI pipeline scaffold.

Pipeline contract:
Snapshot -> SeriesBuilder -> UiCandidateAssembler -> RulePipeline
-> LayoutCompiler -> ViewModelAdapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapter import AnimeFranchiseUiPayload, ViewModelAdapter
from .assembler import UiCandidateAssembler
from .engine import RulePipeline
from .layout import LayoutCompiler
from .no_series_continuity import (
    build_component_entries,
    build_component_relations,
)
from .presets import DefaultUiPreset
from .rule_types import RuleContext, RulePack
from .series import SeriesBuilder

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot


class AnimeFranchiseUiPipeline:
    """Execute fixed-Series + dynamic-secondary UI projection from snapshot.

    Returns adapter-shaped payload for view compatibility; placement business logic
    remains in rule packs, not in adapter/template layers.
    """

    def __init__(self, *, preset: tuple[RulePack, ...] = DefaultUiPreset):
        self.series_builder = SeriesBuilder()
        self.candidate_assembler = UiCandidateAssembler()
        self.rule_pipeline = RulePipeline(list(preset))
        self.layout_compiler = LayoutCompiler()
        self.adapter = ViewModelAdapter()

    def run(self, snapshot: AnimeFranchiseSnapshot) -> AnimeFranchiseUiPayload:
        series_block = self.series_builder.build(snapshot)
        candidates = self.candidate_assembler.build(snapshot)
        context = RuleContext(snapshot=snapshot)
        self.rule_pipeline.run(candidates=candidates, context=context)
        sections = self.layout_compiler.compile(candidates=candidates, context=context)
        if snapshot.has_series_line:
            continuity_component_entries = []
            continuity_component_relations = []
        else:
            continuity_component_entries = build_component_entries(snapshot)
            continuity_component_relations = build_component_relations(snapshot)

        return self.adapter.adapt(
            root_media_id=snapshot.root_node.media_id,
            display_title=snapshot.root_node.title,
            series_block=series_block,
            sections=sections,
            canonical_root_media_id=snapshot.canonical_root_media_id,
            has_series_line=snapshot.has_series_line,
            continuity_component_media_ids=[
                node.media_id for node in snapshot.continuity_component
            ],
            continuity_component_entries=continuity_component_entries,
            continuity_component_relations=continuity_component_relations,
        )


__all__ = [
    "AnimeFranchiseUiPayload",
    "AnimeFranchiseUiPipeline",
]
