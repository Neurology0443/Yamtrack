"""UI policy profiles layered on top of common anime franchise UI rules.

Unlike import profiles (which select IDs to create), UI profiles tune presentation
policy after base rule classification: visibility, section reassignment, section
sorting, and section title overrides.

Illustrative customization patterns (pedagogical examples, not mandatory business
rules):
- hide a relation type globally via ``hidden_relation_types = frozenset({"character"})``
- reclassify specific spin-offs from ``related_series`` to ``specials`` when their
  media type is special-like (e.g. ``special`` / ``tv_special``)
- sort ``related_series`` by editorial intent (e.g. spin-offs first), then by
  continuity link/date tie-breakers
"""

from __future__ import annotations

from functools import cached_property

from app.services.anime_franchise_types import AnimeFranchiseCandidate


class BaseUiProfile:
    """Declarative + targeted hooks for UI customization without rebuilding UI."""

    key = "default"
    hidden_relation_types: frozenset[str] = frozenset()
    hidden_media_types: frozenset[str] = frozenset()
    hidden_titles: frozenset[str] = frozenset()

    def is_candidate_visible(self, candidate: AnimeFranchiseCandidate) -> bool:
        """Return whether a classified candidate should remain visible.

        Title matching is normalized with ``strip()`` + ``casefold()`` on both
        candidate titles and configured ``hidden_titles``.
        """

        normalized_title = self._normalize_title(candidate.title)
        if candidate.relation_type in self.hidden_relation_types:
            return False
        if candidate.media_type in self.hidden_media_types:
            return False
        return normalized_title not in self.normalized_hidden_titles

    def target_section_key(
        self,
        candidate: AnimeFranchiseCandidate,
        default_section_key: str,
    ) -> str:
        """Return section key override for a candidate (or default key)."""

        return default_section_key

    def sort_section_candidates(
        self,
        section_key: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> list[AnimeFranchiseCandidate]:
        """Return sorted candidates for one section."""

        return candidates

    def section_title(
        self,
        section_key: str,
        default_title: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> str:
        """Return final section title for rendering."""

        return default_title

    @staticmethod
    def _normalize_title(title: str) -> str:
        return title.strip().casefold()

    @cached_property
    def normalized_hidden_titles(self) -> frozenset[str]:
        """Return hidden titles normalized once per profile instance."""
        return frozenset(self._normalize_title(title) for title in self.hidden_titles)


class DefaultUiProfile(BaseUiProfile):
    """Default no-op profile preserving existing UI behavior."""

    key = "default"


class NoCharacterRelationsUiProfile(BaseUiProfile):
    """Simple policy profile that hides character relation entries."""

    key = "no_character"
    hidden_relation_types = frozenset({"character"})


class CuratedUiProfile(BaseUiProfile):
    """Concrete policy profile kept as pedagogical and regression reference.

    Demonstrates (illustrative policy only): hide entries, reclassify section,
    custom section sorting, and section title rename while keeping common rule
    classification as base.
    """

    key = "curated"
    RELATED_SECTION_RENAME = "Spin-offs & Related"
    RECLASSIFY_SPIN_OFF_MEDIA_TYPES = frozenset({"special", "tv_special"})

    hidden_relation_types = frozenset({"character"})
    hidden_titles = frozenset(
        {
            "Other Noise",
            "Preview Short",
        }
    )

    def target_section_key(
        self,
        candidate: AnimeFranchiseCandidate,
        default_section_key: str,
    ) -> str:
        if (
            default_section_key == "related_series"
            and candidate.relation_type == "spin_off"
            and candidate.media_type in self.RECLASSIFY_SPIN_OFF_MEDIA_TYPES
        ):
            return "specials"
        return default_section_key

    def sort_section_candidates(
        self,
        section_key: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> list[AnimeFranchiseCandidate]:
        if section_key == "related_series":
            return sorted(candidates, key=self._related_series_key)
        if section_key == "specials":
            return sorted(candidates, key=self._specials_key)
        return candidates

    def section_title(
        self,
        section_key: str,
        default_title: str,
        candidates: list[AnimeFranchiseCandidate],
    ) -> str:
        if section_key == "related_series":
            return self.RELATED_SECTION_RENAME
        return default_title

    @staticmethod
    def _related_series_key(candidate: AnimeFranchiseCandidate) -> tuple:
        relation_rank = 0 if candidate.relation_type == "spin_off" else 1
        linked_index = candidate.linked_series_line_index if candidate.linked_series_line_index is not None else 10_000
        date_value = candidate.start_date.isoformat() if candidate.start_date else "9999-12-31"
        return (relation_rank, linked_index, date_value, int(candidate.media_id))

    @staticmethod
    def _specials_key(candidate: AnimeFranchiseCandidate) -> tuple:
        media_type_rank = {"special": 0, "tv_special": 1}.get(candidate.media_type, 2)
        linked_index = candidate.linked_series_line_index if candidate.linked_series_line_index is not None else 10_000
        date_value = candidate.start_date.isoformat() if candidate.start_date else "9999-12-31"
        return (media_type_rank, linked_index, date_value, int(candidate.media_id))


UI_PROFILES: dict[str, type[BaseUiProfile]] = {
    "default": DefaultUiProfile,
    "no_character": NoCharacterRelationsUiProfile,
    "curated": CuratedUiProfile,
}


def get_ui_profile(profile_key: str = "default") -> BaseUiProfile:
    """Return UI profile instance by key."""

    if profile_key not in UI_PROFILES:
        msg = f"Unsupported UI profile '{profile_key}'"
        raise ValueError(msg)
    return UI_PROFILES[profile_key]()


__all__ = [
    "BaseUiProfile",
    "DefaultUiProfile",
    "NoCharacterRelationsUiProfile",
    "CuratedUiProfile",
    "UI_PROFILES",
    "get_ui_profile",
]
