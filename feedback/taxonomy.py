"""Failure taxonomy (T-89): every failure anywhere in the pipeline lands in exactly one
category, and the category decides where it is routed (feedback/router.py)."""

from __future__ import annotations

from enum import StrEnum

import sqlglot

from ast_.validate import AstValidationError
from cag.templates import TemplateNotFoundError
from codegen.common import UnsupportedAstError
from common.groq_client import GroqClientError
from dag.builder import UnsupportedIntentError
from graph_eng.toposort import CycleError
from ir.lowering import UnmappedNodeTypeError
from ir.registry_check import DatabaseUnavailableError, SchemaDriftError
from ir.typecheck import IrTypeError
from nlu.groq_parser import GroqParseError
from plantdb.catalog import UnknownColumnError, UnknownTableError
from plantdb.plants import UnknownPlantError
from sandbox.cost_check import CostMismatchError
from sandbox.result_check import ResultShapeError
from sandbox.runner import SandboxError


class FailureCategory(StrEnum):
    SYNTAX_ERROR = "syntax_error"  # generated code does not parse
    SEMANTIC_MISMATCH = "semantic_mismatch"  # plan/code is valid but wrong or inexpressible
    INTENT_MISMATCH = "intent_mismatch"  # the question itself was misunderstood or unsupported
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"  # row cap or similar hard limit
    PERMISSION = "permission"  # forbidden operation or database not reachable
    SCHEMA_DRIFT = "schema_drift"  # database no longer matches the catalog


C = FailureCategory
# Exception class -> category. Subclasses inherit; the registry test requires every
# failure-raising class in the repo to appear here.
REGISTRY: dict[type[BaseException], FailureCategory] = {
    sqlglot.errors.ParseError: C.SYNTAX_ERROR,
    SyntaxError: C.SYNTAX_ERROR,
    IrTypeError: C.SEMANTIC_MISMATCH,
    AstValidationError: C.SEMANTIC_MISMATCH,
    UnsupportedAstError: C.SEMANTIC_MISMATCH,
    TemplateNotFoundError: C.SEMANTIC_MISMATCH,
    UnmappedNodeTypeError: C.SEMANTIC_MISMATCH,
    CycleError: C.SEMANTIC_MISMATCH,
    ResultShapeError: C.SEMANTIC_MISMATCH,
    CostMismatchError: C.SEMANTIC_MISMATCH,
    UnsupportedIntentError: C.INTENT_MISMATCH,
    UnknownPlantError: C.INTENT_MISMATCH,
    UnknownTableError: C.INTENT_MISMATCH,
    UnknownColumnError: C.INTENT_MISMATCH,
    SchemaDriftError: C.SCHEMA_DRIFT,
    DatabaseUnavailableError: C.PERMISSION,
    GroqParseError: C.INTENT_MISMATCH,
    GroqClientError: C.TIMEOUT,
}

_STAGE_TO_CATEGORY = {
    "timeout": C.TIMEOUT,
    "row_limit": C.RESOURCE_LIMIT,
    "permission": C.PERMISSION,
    "schema_drift": C.SCHEMA_DRIFT,
}


# Everything the retry layer is allowed to catch: known failure types only, so a genuine bug
# (TypeError, AttributeError, ...) still surfaces instead of being retried.
CATCHABLE: tuple[type[BaseException], ...] = (
    ValueError,
    KeyError,
    SandboxError,
    sqlglot.errors.SqlglotError,
    SyntaxError,
)


class UnclassifiedFailure(TypeError):
    """A failure type nobody registered. Fix by adding it to REGISTRY."""


def classify_sandbox_error(exc: SandboxError) -> FailureCategory:
    if exc.stage in _STAGE_TO_CATEGORY:
        return _STAGE_TO_CATEGORY[exc.stage]
    low = exc.message.lower()
    if exc.stage == "static_validation":
        return C.SYNTAX_ERROR if "does not parse" in low else C.PERMISSION
    # runtime errors from the engine: a missing table/column means the database drifted
    if any(s in low for s in ("no such column", "no such table", "does not exist", "not found")):
        return C.SCHEMA_DRIFT
    return C.SEMANTIC_MISMATCH


def classify(exc: BaseException) -> FailureCategory:
    if isinstance(exc, SandboxError):
        return classify_sandbox_error(exc)
    for cls in type(exc).__mro__:
        if cls in REGISTRY:
            return REGISTRY[cls]
    raise UnclassifiedFailure(
        f"no failure category registered for {type(exc).__module__}.{type(exc).__name__}"
    )
