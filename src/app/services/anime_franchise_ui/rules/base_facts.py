"""Pack reserved for future candidate fact-enrichment.

This stage may later normalize cross-candidate signals, but it intentionally
contains no business logic in the current step.
"""

from __future__ import annotations

from app.services.anime_franchise_ui.rule_types import RulePack

BaseFactsRules = RulePack(key="base_facts", rules=())
