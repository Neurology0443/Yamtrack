"""Compile rule-assigned candidates into ordered secondary sections."""

from __future__ import annotations

from collections import defaultdict

from .candidates import UiCandidate
from .rule_types import CompiledSection, RuleContext, SectionDefinition


class LayoutCompiler:
    """Compile dynamic sections from candidate section keys and section definitions."""

    def compile(
        self,
        *,
        candidates: list[UiCandidate],
        context: RuleContext,
    ) -> list[CompiledSection]:
        grouped: dict[str, list[UiCandidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.hidden or not candidate.section_key:
                continue
            grouped[candidate.section_key].append(candidate)

        section_defs = dict(context.sections)
        for section_key in grouped:
            section_defs.setdefault(
                section_key,
                SectionDefinition(
                    key=section_key,
                    title=section_key.replace("_", " ").title(),
                ),
            )

        sections: list[CompiledSection] = []
        for key, definition in section_defs.items():
            entries = grouped.get(key, [])
            if not entries and definition.hidden_if_empty:
                continue
            sections.append(
                CompiledSection(
                    key=definition.key,
                    title=definition.title,
                    order=definition.order,
                    hidden_if_empty=definition.hidden_if_empty,
                    entries=entries,
                )
            )

        return sorted(sections, key=lambda section: (section.order, section.key))
