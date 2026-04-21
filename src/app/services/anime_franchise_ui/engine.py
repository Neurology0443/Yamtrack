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
                    if rule.when(candidate, context):
                        for action in rule.actions:
                            action(candidate, context)
        return context
