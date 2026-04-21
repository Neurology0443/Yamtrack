"""Base facts rules.

Intentionally minimal for step 1: this pack is the extension point where
future fact-derivation rules can enrich candidate metadata.
"""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import RulePack

BaseFactsRules = RulePack(key="base_facts", rules=())
