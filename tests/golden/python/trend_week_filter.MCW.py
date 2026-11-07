# Query: weekly freight cost for DHL
import pandas as pd


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT dispatch_date, carrier, freight_cost_usd FROM dispatch")
    # n2 filter
    df2 = df1[df1["carrier"] == "DHL"]
    # n3 window
    df3 = df2.assign(dispatch_date_week=pd.to_datetime(df2["dispatch_date"]).dt.strftime("%Y-W%W"))
    # n4 aggregate
    df4 = (
        df3.groupby(["dispatch_date_week"], as_index=False)["freight_cost_usd"]
        .sum()
        .rename(columns={"freight_cost_usd": "sum_freight_cost_usd"})
    )
    # n5 output
    df5 = df4[["dispatch_date_week", "sum_freight_cost_usd"]].reset_index(drop=True)
    return df5
