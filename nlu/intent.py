"""Parsed-intent model: what NLU hands to confirm and the DAG builder."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from dag.model import AggregateOp, FilterOperator, FilterValue, Granularity, SortDirection
from nlu.taxonomy import IntentType, is_out_of_scope
from plantdb.catalog import JOIN_KEY, tables_for_columns

__all__ = ["IntentFilter", "IntentHaving", "IntentType", "ParsedIntent", "is_out_of_scope"]


class IntentFilter(BaseModel):
    column: str = Field(min_length=1)
    operator: FilterOperator
    value: FilterValue
    # "avg": compare against the average of this column ("cost more than the average");
    # the pipeline replaces `value` with that number before planning.
    relative_to: Literal["avg"] | None = None


class IntentHaving(BaseModel):
    """A condition on the aggregated result ("carriers with more than 500 shipments")."""

    operator: FilterOperator
    value: float | None = None
    # "overall_avg": compare against the average ("charge more than the average");
    # the pipeline fills `value` for averages, the merge step uses the mean of the groups otherwise.
    relative_to: Literal["overall_avg"] | None = None


class ParsedIntent(BaseModel):
    query: str
    intent_type: IntentType
    metric: str | None = None
    agg: AggregateOp | None = None
    group_by: list[str] = Field(default_factory=list)
    filters: list[IntentFilter] = Field(default_factory=list)
    select_columns: list[str] = Field(default_factory=list)
    sort_direction: SortDirection | None = None
    limit: int | None = Field(default=None, gt=0)
    granularity: Granularity | None = None
    time_column: str | None = None
    horizon: int | None = Field(default=None, gt=0)
    plants: list[str] = Field(default_factory=list)  # empty means every plant
    compare_by_plant: bool = False
    keep_values: dict[str, list[str]] = Field(default_factory=dict)  # post-merge row filter
    having: list[IntentHaving] = Field(default_factory=list)  # post-merge condition on the result
    confidence: float = Field(ge=0.0, le=1.0)
    entity_confidence: dict[str, float] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)

    def referenced_columns(self) -> list[str]:
        cols: list[str] = []
        if self.metric:
            cols.append(self.metric)
        cols += [c for c in self.group_by if c != "plant"]
        cols += [f.column for f in self.filters]
        cols += self.select_columns
        if self.time_column:
            cols.append(self.time_column)
        seen: dict[str, None] = {}
        for c in cols:
            seen.setdefault(c, None)
        return list(seen)

    def tables(self) -> list[str]:
        return tables_for_columns(self.referenced_columns())

    @property
    def is_row_listing(self) -> bool:
        return self.intent_type in (IntentType.FILTER, IntentType.JOIN)


_ = JOIN_KEY  # re-exported for callers that build row listings
