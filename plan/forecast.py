"""Linear-trend forecast over monthly buckets (used after the cross-plant merge, and
embedded verbatim in generated Python when a forecast node is lowered)."""

import pandas as pd


def _linear_forecast(df, period_col, value_col, horizon):
    s = df[value_col].astype(float).reset_index(drop=True)
    x = pd.Series(range(len(s)), dtype=float)
    slope = x.cov(s) / x.var() if len(s) > 1 and x.var() else 0.0
    intercept = s.mean() - slope * x.mean()
    last = pd.Period(str(df[period_col].iloc[-1]), freq="M")
    future = pd.DataFrame(
        {
            period_col: [str(last + i) for i in range(1, horizon + 1)],
            value_col: [intercept + slope * (len(s) + i) for i in range(horizon)],
        }
    )
    history = df[[period_col, value_col]].reset_index(drop=True)
    return pd.concat(
        [history.assign(kind="actual"), future.assign(kind="forecast")], ignore_index=True
    )


linear_forecast = _linear_forecast
