"""Rule actions for candidate placement and section-definition mutation.

Actions stay intentionally lightweight: they mutate rule context/candidates and
delegate all business decisions to rule predicates and rule ordering.
"""

from __future__ import annotations

from .rule_types import RuleContext, SectionDefinition


def ensure_section(
    *,
    key: str,
    title: str,
    order: int = 1000,
    hidden_if_empty: bool = True,
    metadata: dict[str, object] | None = None,
):
    def _action(_candidate, context: RuleContext) -> None:
        existing = context.sections.get(key)
        if existing is None:
            context.sections[key] = SectionDefinition(
                key=key,
                title=title,
                order=order,
                hidden_if_empty=hidden_if_empty,
                metadata=dict(metadata or {}),
            )
            return

        existing.title = title
        existing.order = order
        existing.hidden_if_empty = hidden_if_empty
        if metadata:
            existing.metadata.update(metadata)

    return _action


def set_section_title(*, key: str, title: str):
    def _action(_candidate, context: RuleContext) -> None:
        definition = context.sections.setdefault(
            key,
            SectionDefinition(
                key=key,
                title=title,
            ),
        )
        definition.title = title

    return _action


def set_section_order(*, key: str, order: int):
    def _action(_candidate, context: RuleContext) -> None:
        definition = context.sections.setdefault(
            key,
            SectionDefinition(
                key=key,
                title=key.replace("_", " ").title(),
            ),
        )
        definition.order = order

    return _action


def set_section_hidden_if_empty(*, key: str, hidden_if_empty: bool):
    def _action(_candidate, context: RuleContext) -> None:
        definition = context.sections.setdefault(
            key,
            SectionDefinition(
                key=key,
                title=key.replace("_", " ").title(),
            ),
        )
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
