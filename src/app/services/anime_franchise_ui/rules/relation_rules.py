"""Pack reserved for future relation-signal driven placement refinements.

No relation-specific business heuristics are enabled at this stage.
"""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import RulePack

RelationRules = RulePack(key="relation_rules", rules=())
