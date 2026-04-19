"""Compatibility shim for UI builder module.

Prefer importing from ``app.services.anime_franchise_ui_builder``.
"""

from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder

AnimeFranchiseUiProfile = AnimeFranchiseUiBuilder

__all__ = ["AnimeFranchiseUiBuilder", "AnimeFranchiseUiProfile"]
