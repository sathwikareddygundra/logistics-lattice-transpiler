# Query: forecast freight cost next 2 months
import pandas as pd


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT dispatch_date, freight_cost_usd FROM dispatch")
    # n2 window
    df2 = df1.assign(dispatch_date_month=pd.to_datetime(df1["dispatch_date"]).dt.strftime("%Y-%m"))
    # n3 aggregate
    df3 = (
        df2.groupby(["dispatch_date_month"], as_index=False)["freight_cost_usd"]
        .sum()
        .rename(columns={"freight_cost_usd": "sum_freight_cost_usd"})
    )
    # n4 output
    df4 = df3[["dispatch_date_month", "sum_freight_cost_usd"]].reset_index(drop=True)
    return df4
