"""Composable rule predicates for UiCandidate evaluation."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .candidates import UiCandidate
from .rule_types import RuleContext

CandidatePredicate = Callable[[UiCandidate, RuleContext], bool]


def always() -> CandidatePredicate:
    return lambda _candidate, _context: True


def all_of(*predicates: CandidatePredicate) -> CandidatePredicate:
    def _predicate(candidate, context: RuleContext) -> bool:
        return all(predicate(candidate, context) for predicate in predicates)

    return _predicate


def any_of(*predicates: CandidatePredicate) -> CandidatePredicate:
    def _predicate(candidate, context: RuleContext) -> bool:
        return any(predicate(candidate, context) for predicate in predicates)

    return _predicate


def media_type_in(media_types: Iterable[str]) -> CandidatePredicate:
    media_types = set(media_types)
    return lambda candidate, _context: candidate.media_type in media_types


def relation_type_in(relation_types: Iterable[str]) -> CandidatePredicate:
    relation_types = set(relation_types)
    return lambda candidate, _context: candidate.relation_type in relation_types


def relation_type_is(relation_type: str) -> CandidatePredicate:
    return lambda candidate, _context: candidate.relation_type == relation_type


def runtime_minutes_lt(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.runtime_minutes is not None and candidate.runtime_minutes < value
    )


def runtime_minutes_lte(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.runtime_minutes is not None and candidate.runtime_minutes <= value
    )


def runtime_minutes_gt(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.runtime_minutes is not None and candidate.runtime_minutes > value
    )


def runtime_minutes_gte(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.runtime_minutes is not None and candidate.runtime_minutes >= value
    )


def runtime_minutes_eq(value: int) -> CandidatePredicate:
    return lambda candidate, _context: candidate.runtime_minutes == value


def episode_count_lt(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.episode_count is not None and candidate.episode_count < value
    )


def episode_count_lte(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.episode_count is not None and candidate.episode_count <= value
    )


def episode_count_gt(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.episode_count is not None and candidate.episode_count > value
    )


def episode_count_gte(value: int) -> CandidatePredicate:
    return lambda candidate, _context: (
        candidate.episode_count is not None and candidate.episode_count >= value
    )


def episode_count_eq(value: int) -> CandidatePredicate:
    return lambda candidate, _context: candidate.episode_count == value
