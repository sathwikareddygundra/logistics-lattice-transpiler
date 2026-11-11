# Query: compare MCW and YCW freight cost
import pandas as pd


def run(read_sql):
    # n1 select
    df1 = read_sql("SELECT freight_cost_usd FROM dispatch")
    # n2 aggregate
    df2 = pd.DataFrame({"sum_freight_cost_usd": [df1["freight_cost_usd"].sum()]})
    # n3 output
    df3 = df2[["sum_freight_cost_usd"]].reset_index(drop=True)
    return df3
