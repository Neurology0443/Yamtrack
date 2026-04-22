"""Rule actions for candidate placement and section-definition mutation.

Actions stay intentionally lightweight: they mutate rule context/candidates and
delegate all business decisions to rule predicates and rule ordering.
"""

from __future__ import annotations

from typing import Any

from .rule_types import RuleContext, SectionDefinition


def _get_or_create_section(
    context: RuleContext,
    *,
    key: str,
    default_title: str | None = None,
) -> SectionDefinition:
    return context.sections.setdefault(
        key,
        SectionDefinition(
            key=key,
            title=default_title or key.replace("_", " ").title(),
        ),
    )


def ensure_section(
    *,
    key: str,
    title: str,
    order: int = 1000,
    hidden_if_empty: bool = True,
    metadata: dict[str, object] | None = None,
):
    def _action(_candidate, context: RuleContext) -> None:
        if key not in context.sections:
            context.sections[key] = SectionDefinition(
                key=key,
                title=title,
                order=order,
                hidden_if_empty=hidden_if_empty,
                metadata=dict(metadata or {}),
            )

    return _action


def set_section_title(*, key: str, title: str):
    def _action(_candidate, context: RuleContext) -> None:
        definition = _get_or_create_section(
            context,
            key=key,
            default_title=title,
        )
        definition.title = title

    return _action


def set_section_order(*, key: str, order: int):
    def _action(_candidate, context: RuleContext) -> None:
        definition = _get_or_create_section(context, key=key)
        definition.order = order

    return _action


def set_section_hidden_if_empty(*, key: str, hidden_if_empty: bool):
    def _action(_candidate, context: RuleContext) -> None:
        definition = _get_or_create_section(context, key=key)
        definition.hidden_if_empty = hidden_if_empty

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


def set_candidate_metadata(key: str, value: Any):
    def _action(candidate, _context: RuleContext) -> None:
        candidate.metadata[key] = value

    return _action
