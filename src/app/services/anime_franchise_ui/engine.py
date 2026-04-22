"""Minimal rule engine for dynamic secondary section placement."""

from __future__ import annotations

from .candidates import UiCandidate
from .rule_types import RuleContext, RulePack


class RulePipeline:
    """Run ordered rule packs against a candidate collection."""

    def __init__(self, packs: list[RulePack]):
        self.packs = packs

    def run(self, *, candidates: list[UiCandidate], context: RuleContext) -> RuleContext:
        for pack in self.packs:
            for rule in pack.rules:
                for candidate in candidates:
                    previous_section = candidate.section_key
                    if rule.when(candidate, context):
                        for action in rule.actions:
                            action(candidate, context)

                    current_section = candidate.section_key
                    if current_section != previous_section:
                        trail = candidate.metadata.setdefault("placement_trace", [])
                        trail.append(
                            {
                                "pack": pack.key,
                                "rule": rule.key,
                                "from": previous_section,
                                "to": current_section,
                                "kind": "initial" if previous_section is None else "override",
                            }
                        )
        return context
