"""Rule actions that mutate UiCandidate placement and section metadata."""

from __future__ import annotations

from .rule_types import RuleContext, SectionDefinition


def ensure_section(
    *,
    key: str,
    title: str,
    order: int = 1000,
    hidden_if_empty: bool = True,
):
    def _action(_candidate, context: RuleContext) -> None:
        context.sections.setdefault(
            key,
            SectionDefinition(
                key=key,
                title=title,
                order=order,
                hidden_if_empty=hidden_if_empty,
            ),
        )

    return _action


def place_in(section_key: str):
    def _action(candidate, _context: RuleContext) -> None:
        candidate.section_key = section_key

    return _action


def hide_candidate():
    def _action(candidate, _context: RuleContext) -> None:
        candidate.hidden = True

    return _action


def add_badge(label: str):
    def _action(candidate, _context: RuleContext) -> None:
        if label not in candidate.badges:
            candidate.badges.append(label)

    return _action
