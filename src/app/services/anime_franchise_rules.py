"""Compatibility shim for UI rules module.

Prefer importing from ``app.services.anime_franchise_ui_rules``.
"""

from app.services.anime_franchise_ui_rules import SECTION_RULES, get_section_rules

__all__ = ["SECTION_RULES", "get_section_rules"]
