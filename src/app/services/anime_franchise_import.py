"""Compatibility re-export for anime franchise import service.

Prefer importing from ``app.services.anime_franchise_import_service``.
"""

from app.services.anime_franchise_import_service import (
    AnimeFranchiseImportService,
    FranchiseImportStats,
)

__all__ = ["AnimeFranchiseImportService", "FranchiseImportStats"]
