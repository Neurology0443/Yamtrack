"""Rule and layout datatypes for anime franchise UI pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshot

    from .candidates import UiCandidate

RulePredicate = Callable[["UiCandidate", "RuleContext"], bool]
RuleAction = Callable[["UiCandidate", "RuleContext"], None]


@dataclass
class SectionDefinition:
    """Dynamic section metadata created or updated by rules."""

    key: str
    title: str
    order: int = 1000
    hidden_if_empty: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class CompiledSection:
    """Output section with resolved entries ready for adapter step."""

    key: str
    title: str
    order: int
    hidden_if_empty: bool
    entries: list[UiCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class Rule:
    """Declarative candidate rule with optional predicate and actions."""

    key: str
    when: RulePredicate
    actions: tuple[RuleAction, ...] = ()


@dataclass(frozen=True)
class RulePack:
    """Ordered group of rules that represent one pipeline stage."""

    key: str
    rules: tuple[Rule, ...] = ()


@dataclass
class RuleContext:
    """Mutable context shared between all rules in one pipeline execution."""

    snapshot: AnimeFranchiseSnapshot
    sections: dict[str, SectionDefinition] = field(default_factory=dict)
    state: dict[str, object] = field(default_factory=dict)
