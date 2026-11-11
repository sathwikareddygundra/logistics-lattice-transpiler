"""Cost and row-count sanity check (T-86): a large gap between the estimate and what really
ran blocks auto-promotion and flags the query for human review."""

from __future__ import annotations

from dataclasses import dataclass

MISMATCH_FACTOR = 10  # an order of magnitude; the same number the rollout rollback rule uses
IGNORE_BELOW_ROWS = 100  # tiny results are never worth blocking on


class CostMismatchError(ValueError):
    stage = "semantic_mismatch"


@dataclass(frozen=True)
class CostVerdict:
    estimated: int
    actual: int
    ratio: float
    block_promotion: bool

    @property
    def message(self) -> str:
        return (
            f"estimated {self.estimated} rows but got {self.actual} "
            f"(off by {self.ratio:.1f}x, limit {MISMATCH_FACTOR}x); needs human review"
        )


def check_cost(estimated: int, actual: int, factor: float = MISMATCH_FACTOR) -> CostVerdict:
    est, act = max(estimated, 1), max(actual, 1)
    ratio = max(est / act, act / est)
    big_enough = max(est, act) >= IGNORE_BELOW_ROWS
    return CostVerdict(estimated, actual, ratio, big_enough and ratio >= factor)
