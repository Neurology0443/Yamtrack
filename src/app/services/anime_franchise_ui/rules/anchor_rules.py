"""Anchor/provenance refinements for direct-series placement compatibility."""

from __future__ import annotations

from app.services.anime_franchise_ui.actions import place_in
from app.services.anime_franchise_ui.rule_types import Rule, RulePack


def _is_direct_or_fallback_anchor(candidate, context) -> bool:
    # Keep this exception tightly scoped: promoted continuity candidates only
    # bypass indirect filtering after they are explicitly placed in
    # `continuity_extras` by earlier placement rules.
    if (
        candidate.metadata.get("is_promoted_continuity")
        and candidate.section_key == "continuity_extras"
    ):
        return True
    if candidate.has_series_line_origin:
        return True
    if (
        context.snapshot.has_series_line
        and candidate.has_root_origin
        and context.snapshot.root_node.media_id
        not in {node.media_id for node in context.snapshot.series_line}
    ):
        return True
    return (
        not context.snapshot.has_series_line
        and candidate.linked_series_line_media_id == context.snapshot.fallback_anchor_media_id
    )


def _is_indirect_without_fallback_anchor(candidate, context) -> bool:
    return not _is_direct_or_fallback_anchor(candidate, context)

AnchorRules = RulePack(
    key="anchor_rules",
    rules=(
        Rule(
            key="indirect_candidates_go_to_ignored",
            when=_is_indirect_without_fallback_anchor,
            actions=(place_in("ignored"),),
        ),
    ),
)
