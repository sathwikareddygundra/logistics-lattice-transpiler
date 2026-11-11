"""Multi-plant execution plan: one branch per plant, merged afterwards (T-39, T-46).

Every aggregate runs inside each plant first (local aggregation, then a
small merge) instead of shipping raw rows. Averages travel as a sum and a
count and are divided after the merge, so the result equals a single-database
answer. A failing branch is isolated: the others still merge and the result
is flagged partial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pandas as pd

from dag.dependencies import window_alias
from dag.model import AggregateOp
from nlu.intent import IntentType, ParsedIntent
from plan.forecast import linear_forecast


@dataclass(frozen=True)
class Branch:
    plant: str
    variant: str  # value | sum | count
    intent: ParsedIntent


def final_alias(intent: ParsedIntent) -> str:
    assert intent.agg is not None and intent.metric is not None
    return f"{intent.agg.value}_{intent.metric}"


def bucket_alias(intent: ParsedIntent) -> str | None:
    if intent.granularity is None:
        return None
    return window_alias(intent.time_column or "dispatch_date", intent.granularity.value)


def group_keys(intent: ParsedIntent) -> list[str]:
    bucket = bucket_alias(intent)
    return ([bucket] if bucket else []) + list(intent.group_by)


def plan_branches(intent: ParsedIntent, plants: list[str]) -> list[Branch]:
    base = intent.model_copy(update={"plants": [], "sort_direction": None, "limit": None})
    if intent.is_row_listing:
        base = intent.model_copy(update={"plants": []})  # per-branch limit is safe
        return [Branch(p, "value", base) for p in plants]
    branches: list[Branch] = []
    for p in plants:
        if intent.agg is AggregateOp.AVG:
            branches.append(Branch(p, "sum", base.model_copy(update={"agg": AggregateOp.SUM})))
            branches.append(Branch(p, "count", base.model_copy(update={"agg": AggregateOp.COUNT})))
        else:
            branches.append(Branch(p, "value", base))
    return branches


_COMPARE = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def apply_having(intent: ParsedIntent, df: pd.DataFrame, alias: str) -> pd.DataFrame:
    """Filter groups on their final aggregated value. This must run after the plants are
    merged: a group's total or average across plants is not its per-plant value."""
    for h in intent.having:
        threshold = h.value
        if threshold is None:  # "above average" for a sum, count, min or max: mean of the groups
            threshold = float(df[alias].mean())
        df = df[_COMPARE[h.operator.value](df[alias], threshold)]
    return df


def _reduce(frames: list[pd.DataFrame], keys: list[str], col: str, how: str) -> pd.DataFrame:
    df = pd.concat(frames, ignore_index=True)
    if not keys:
        return pd.DataFrame({col: [getattr(df[col], how)()]})
    return cast(pd.DataFrame, df.groupby(keys, as_index=False, dropna=False)[col].agg(how))


def merge(intent: ParsedIntent, frames: dict[tuple[str, str], pd.DataFrame]) -> pd.DataFrame:
    """Combine per-plant branch frames into the final answer."""
    if intent.is_row_listing:
        df = pd.concat(list(frames.values()), ignore_index=True)
        df = df.sort_values("invoice_number", kind="stable").head(intent.limit or len(df))
        return df.reset_index(drop=True)

    alias = final_alias(intent)
    keys = group_keys(intent)
    plant_key = ["plant"] if intent.compare_by_plant else []
    all_keys = plant_key + keys

    def tag(variant: str) -> list[pd.DataFrame]:
        out = []
        for (plant, v), frame in frames.items():
            if v == variant:
                out.append(frame.assign(plant=plant) if plant_key else frame)
        return out

    if intent.agg is AggregateOp.AVG:
        sums = _reduce(tag("sum"), all_keys, f"sum_{intent.metric}", "sum")
        counts = _reduce(tag("count"), all_keys, f"count_{intent.metric}", "sum")
        if all_keys:
            df = sums.merge(counts, on=all_keys)
        else:
            df = pd.concat([sums, counts], axis=1)
        df[alias] = df[f"sum_{intent.metric}"] / df[f"count_{intent.metric}"]
        df = df[[*all_keys, alias]]
    else:
        assert intent.agg is not None
        how = {
            AggregateOp.SUM: "sum", AggregateOp.COUNT: "sum",
            AggregateOp.MIN: "min", AggregateOp.MAX: "max",
        }[intent.agg]  # fmt: skip
        df = _reduce(tag("value"), all_keys, alias, how)

    for col, values in intent.keep_values.items():
        df = df[df[col].isin(values)]
    df = apply_having(intent, df, alias)

    if intent.intent_type is IntentType.RANK:
        asc = intent.sort_direction is not None and intent.sort_direction.value == "asc"
        df = df.sort_values(
            [alias, *all_keys], ascending=[asc] + [True] * len(all_keys), kind="stable"
        )
        df = df.head(intent.limit or len(df))
    elif all_keys:
        df = df.sort_values(all_keys, kind="stable")
    df = df.reset_index(drop=True)

    if intent.intent_type is IntentType.FORECAST and intent.horizon:
        bucket = bucket_alias(intent)
        assert bucket is not None
        group_cols = plant_key + [k for k in keys if k != bucket]
        if group_cols:  # forecast each series separately
            parts = [
                linear_forecast(g.sort_values(bucket), bucket, alias, intent.horizon).assign(
                    **dict(
                        zip(group_cols, name if isinstance(name, tuple) else (name,), strict=True)
                    )
                )
                for name, g in df.groupby(group_cols)
            ]
            df = pd.concat(parts, ignore_index=True)[[*group_cols, bucket, alias, "kind"]]
        else:
            df = linear_forecast(df, bucket, alias, intent.horizon)
    return df
