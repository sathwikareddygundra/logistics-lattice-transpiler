"""Failure routing and the shared retry budget (T-90, T-91, T-92).

Codegen-level failures (syntax, semantic) are retried with the error turned into a concrete
change (quote every identifier, or switch target). Intent-level failures reopen the confirm
step instead. Both paths draw on ONE budget, so a query can never bounce between them forever.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ast_.nodes import AstTarget
from codegen.common import CodegenHints
from feedback.diagnostics import Diagnostic
from feedback.taxonomy import CATCHABLE
from feedback.taxonomy import FailureCategory as C

MAX_TOTAL_ATTEMPTS = 3
GIVE_UP = (
    "Sorry, I couldn't produce a reliable answer after {n} attempts ({reason}). "
    "Please rephrase the question or ask for a simpler breakdown."
)
T = TypeVar("T")


@dataclass
class RetryBudget:
    """One budget for every retry path (codegen retries and confirm reopenings).
    First attempts are free; each retry or reopening spends one."""

    max_total: int = MAX_TOTAL_ATTEMPTS
    used: int = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_total

    def spend(self) -> None:
        self.used += 1


@dataclass(frozen=True)
class Action:
    kind: str  # retry_codegen | reopen_confirm | stop
    target: AstTarget
    hints: CodegenHints
    reason: str


@dataclass
class Attempt:
    target: AstTarget
    hints: CodegenHints
    category: str = ""
    message: str = ""


class NeedsConfirmation(Exception):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class GiveUp(Exception):
    def __init__(self, message: str, diagnostics: list[Diagnostic]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def next_action(
    category: C, target: AstTarget, hints: CodegenHints, tried: list[Attempt], budget: RetryBudget
) -> Action:
    stop = Action("stop", target, hints, "no automatic retry for this category")
    if budget.exhausted:
        return Action("stop", target, hints, "retry budget exhausted")
    if category is C.INTENT_MISMATCH:
        return Action("reopen_confirm", target, hints, "the question may have been misunderstood")
    if category is C.SYNTAX_ERROR and not hints.quote_all_identifiers:
        return Action(
            "retry_codegen", target, CodegenHints(quote_all_identifiers=True), "quote identifiers"
        )
    if category is C.SEMANTIC_MISMATCH:
        other = AstTarget.PYTHON if target is AstTarget.SQL else AstTarget.SQL
        if not any(a.target is other for a in tried):
            return Action("retry_codegen", other, hints, f"switch target to {other.value}")
    return stop


def run_with_retries(
    attempt: Callable[[AstTarget, CodegenHints], T],
    diagnose: Callable[[BaseException, AstTarget], Diagnostic],
    budget: RetryBudget,
    target: AstTarget,
    catch: tuple[type[BaseException], ...] = CATCHABLE,
) -> tuple[T, list[Attempt]]:
    """Run `attempt`; on a classified failure follow next_action until success, a confirm
    reopening, or the shared budget runs out."""
    hints = CodegenHints()
    history: list[Attempt] = []
    diagnostics: list[Diagnostic] = []
    while True:
        record = Attempt(target, hints)
        history.append(record)
        try:
            return attempt(target, hints), history
        except catch as exc:
            diag = diagnose(exc, target)
            diagnostics.append(diag)
            record.category, record.message = diag.category.value, diag.message
            action = next_action(diag.category, target, hints, history, budget)
            if action.kind == "reopen_confirm":
                budget.spend()
                raise NeedsConfirmation(diag) from exc
            if action.kind == "stop":
                reason = diag.message if budget.exhausted else action.reason
                raise GiveUp(
                    GIVE_UP.format(n=len(history), reason=reason[:120]), diagnostics
                ) from exc
            budget.spend()  # only retries draw on the budget; a first attempt is free
            target, hints = action.target, action.hints
