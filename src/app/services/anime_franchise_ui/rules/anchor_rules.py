"""Pack reserved for future anchor/provenance-aware rule refinements.

It stays intentionally empty until anchoring behavior is specified in detail.
"""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import RulePack

AnchorRules = RulePack(key="anchor_rules", rules=())
