"""Parsed-intent model: what NLU hands to confirm and the DAG builder."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from dag.model import AggregateOp, FilterOperator, FilterValue, SortDirection


class IntentType(StrEnum):
    AGGREGATION = "aggregation"
    RANK = "rank"
    OUT_OF_SCOPE = "out_of_scope"


class IntentFilter(BaseModel):
    column: str = Field(min_length=1)
    operator: FilterOperator
    value: FilterValue


class ParsedIntent(BaseModel):
    query: str
    intent_type: IntentType
    table: str | None = None
    metric: str | None = None
    agg: AggregateOp | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[IntentFilter] = Field(default_factory=list)
    sort_direction: SortDirection | None = None
    limit: int | None = Field(default=None, gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
